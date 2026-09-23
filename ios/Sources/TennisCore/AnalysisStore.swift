import Foundation
import CSQLite

/// Each checkpoint atomically stores output rows, tracker/event context and the next frame.
/// WAL keeps review reads independent from an analysis writer. Callers never retain decoded video frames here.
public final class AnalysisStore: @unchecked Sendable {
    private var db: OpaquePointer?; private let lock = NSRecursiveLock()
    private let transient = unsafeBitCast(-1, to: sqlite3_destructor_type.self)
    public init(url: URL, identity: ResumeIdentity) throws {
        guard sqlite3_open_v2(url.path,&db,SQLITE_OPEN_READWRITE|SQLITE_OPEN_CREATE|SQLITE_OPEN_FULLMUTEX,nil)==SQLITE_OK else { throw PackageError.database("Cannot open store") }
        do {
            try sql("PRAGMA journal_mode=WAL"); try sql("PRAGMA synchronous=FULL"); try sql("PRAGMA busy_timeout=5000")
            try sql("CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value BLOB NOT NULL)")
            try sql("CREATE TABLE IF NOT EXISTS frames(frame INTEGER PRIMARY KEY, timestamp REAL NOT NULL UNIQUE, payload BLOB NOT NULL)")
            try sql("CREATE INDEX IF NOT EXISTS frames_time ON frames(timestamp)")
            try sql("CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY, start REAL NOT NULL, payload BLOB NOT NULL)")
            try sql("CREATE TABLE IF NOT EXISTS track_samples(sequence INTEGER PRIMARY KEY, bucket TEXT NOT NULL, payload BLOB NOT NULL)")
            try sql("CREATE INDEX IF NOT EXISTS track_buckets ON track_samples(bucket)")
            if let old: ResumeIdentity = try metadata("identity") {
                guard old == identity else { throw PackageError.incompatibleResume }
            } else {
                try setMetadata("identity", identity); try setMetadata("state",RuntimeState()); try setMetadata("status",AnalysisStatus.paused)
            }
            if try metadata("trackAccounting") as TrackAccounting? == nil {
                try sql("BEGIN IMMEDIATE")
                do {
                    if let graph: EvidenceBundle = try metadata("evidence") { try writeEvidence(graph) }
                    else { try setMetadata("trackAccounting", TrackAccounting()) }
                    try sql("COMMIT")
                } catch { try? sql("ROLLBACK"); throw error }
            }
        } catch { sqlite3_close(db); db=nil; throw error }
    }
    deinit { sqlite3_close(db) }
    private func synchronized<T>(_ action: () throws -> T) rethrows -> T { lock.lock(); defer { lock.unlock() }; return try action() }
    private func failure() -> PackageError { .database(String(cString: sqlite3_errmsg(db))) }
    private func sql(_ query: String) throws { guard sqlite3_exec(db,query,nil,nil,nil)==SQLITE_OK else { throw failure() } }
    private func statement<T>(_ query:String,_ action:(OpaquePointer)throws->T)throws->T {
        var s: OpaquePointer?; guard sqlite3_prepare_v2(db,query,-1,&s,nil)==SQLITE_OK, let s else { throw failure() }
        defer { sqlite3_finalize(s) }; return try action(s)
    }
    private func bind(_ value:String,to statement:OpaquePointer,at index:Int32) { _ = sqlite3_bind_text(statement,index,value,-1,transient) }
    private func bind(_ value:Data,to statement:OpaquePointer,at index:Int32) {
        _ = value.withUnsafeBytes { sqlite3_bind_blob(statement,index,$0.baseAddress,Int32($0.count),transient) }
    }
    private func rowData(_ statement:OpaquePointer,column:Int32)->Data {
        let count=Int(sqlite3_column_bytes(statement,column)); return Data(bytes: sqlite3_column_blob(statement,column),count: count)
    }
    private func done(_ statement:OpaquePointer)throws { guard sqlite3_step(statement)==SQLITE_DONE else { throw failure() } }
    private func metadata<T:Decodable>(_ key:String)throws->T? {
        try statement("SELECT value FROM meta WHERE key=?") { s in
            bind(key,to:s,at:1); let result=sqlite3_step(s)
            if result==SQLITE_DONE { return nil }; guard result==SQLITE_ROW else { throw failure() }
            return try ContractJSON.decoder().decode(T.self,from:rowData(s,column:0))
        }
    }
    private func setMetadata<T:Encodable>(_ key:String,_ value:T)throws {
        try statement("INSERT INTO meta(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value") { s in
            bind(key,to:s,at:1); bind(try ContractJSON.encoder().encode(value),to:s,at:2); try done(s)
        }
    }
    private struct TrackAccounting: Codable { var rows = 0; var bytes = 0 }
    private func appendTracks(_ samples: [PlayerPosition], preserveAll: Bool = false) throws -> Bool {
        var accounting: TrackAccounting = try metadata("trackAccounting") ?? TrackAccounting()
        let originalCount = accounting.rows
        for sample in samples {
            let bucket = try TrackSummaryBuilder.bucket(sample)
            if !preserveAll {
                let exists = try statement("SELECT 1 FROM track_samples WHERE bucket=? LIMIT 1") { s in
                    bind(bucket, to: s, at: 1)
                    let code = sqlite3_step(s)
                    guard code == SQLITE_ROW || code == SQLITE_DONE else { throw failure() }
                    return code == SQLITE_ROW
                }
                if exists { continue }
            }
            let data = try ContractJSON.encoder().encode(sample)
            accounting.rows += 1; accounting.bytes += data.count + 1
            try EvidenceBundle.require(accounting.rows <= EvidenceBundle.maxRows && accounting.bytes <= EvidenceBundle.maxBytes, "Track summary exceeds portable limits")
            try statement("INSERT INTO track_samples(bucket,payload) VALUES(?,?)") { s in
                bind(bucket, to: s, at: 1); bind(data, to: s, at: 2); try done(s)
            }
        }
        if accounting.rows != originalCount { try setMetadata("trackAccounting", accounting) }
        return accounting.rows != originalCount
    }
    private func readEvidence() throws -> EvidenceBundle? {
        guard var graph: EvidenceBundle = try metadata("evidence") else { return nil }
        graph.tracks = try statement("SELECT payload FROM track_samples ORDER BY sequence") { s in
            var rows: [PlayerPosition] = [], code = sqlite3_step(s)
            while code == SQLITE_ROW {
                rows.append(try ContractJSON.decoder().decode(PlayerPosition.self, from: rowData(s, column: 0)))
                code = sqlite3_step(s)
            }
            guard code == SQLITE_DONE else { throw failure() }; return rows
        }
        return graph
    }
    /// Call inside a transaction. Whole replacements occur only on import or review edits.
    private func writeEvidence(_ graph: EvidenceBundle) throws {
        try sql("DELETE FROM track_samples")
        try setMetadata("trackAccounting", TrackAccounting())
        _ = try appendTracks(graph.tracks, preserveAll: true)
        var header = graph; header.tracks = []
        try setMetadata("evidence", header)
    }
    public func state()throws->RuntimeState { try synchronized { try metadata("state") ?? RuntimeState() } }
    public func status()throws->AnalysisStatus { try synchronized { try metadata("status") ?? .paused } }
    public func setStatus(_ value:AnalysisStatus)throws { try synchronized { try setMetadata("status",value) } }
    public func corrections()throws->Corrections { try synchronized { try metadata("corrections") ?? Corrections() } }
    public func saveCorrections(_ value:Corrections)throws {
        try synchronized {
            try sql("BEGIN IMMEDIATE")
            do {
                let previous = try corrections()
                try setMetadata("corrections", value)
                if previous != value, var graph = try readEvidence() {
                    graph.metrics.metrics = []; graph.insights.insights = []
                    if previous.court != value.court {
                        let reviewed = graph.tracks.filter(\.reviewed)
                        var summary = try TrackSummaryBuilder(existing: reviewed)
                        var activeCourt: Court?, previousScene: Int?
                        try statement("SELECT payload FROM frames ORDER BY frame") { s in
                            var code = sqlite3_step(s)
                            while code == SQLITE_ROW {
                                var frame = try ContractJSON.decoder().decode(FrameRecord.self, from: rowData(s, column: 0))
                                if previousScene != frame.scene || frame.cameraMoving || frame.cut { activeCourt = nil }
                                previousScene = frame.scene
                                if let points = value.court[String(frame.frame)] { activeCourt = try Court(points: points) }
                                frame.court = activeCourt
                                for player in frame.players {
                                    try summary.append(PlayerPositionEstimator.sample(player: player, frame: frame))
                                }
                                code = sqlite3_step(s)
                            }
                            guard code == SQLITE_DONE else { throw failure() }
                        }
                        graph.tracks = summary.samples
                        try setMetadata("automaticTrackSampling", TrackSummaryBuilder.version)
                    }
                    try writeEvidence(graph)
                }
                try sql("COMMIT")
            } catch { try? sql("ROLLBACK"); throw error }
        }
    }
    public func checkpoint(frames:[FrameRecord],events:[AnalysisEvent],state:RuntimeState,status:AnalysisStatus = .running)throws {
        try synchronized {
            try sql("BEGIN IMMEDIATE")
            do {
                let old:RuntimeState = try metadata("state") ?? RuntimeState()
                var next=old.nextFrame, timestamp=old.lastTimestamp
                for frame in frames {
                    try frame.validate()
                    guard frame.frame==next,frame.timestamp>timestamp else { throw PackageError.invalid("Checkpoint frames must be contiguous and timestamps strictly increasing") }
                    try statement("INSERT INTO frames(frame,timestamp,payload) VALUES(?,?,?)") { s in
                        sqlite3_bind_int64(s,1,Int64(frame.frame)); sqlite3_bind_double(s,2,frame.timestamp)
                        bind(try ContractJSON.encoder().encode(frame),to:s,at:3); try done(s)
                    }
                    next += 1; timestamp=frame.timestamp
                }
                guard state.nextFrame==next,state.lastTimestamp==timestamp else { throw PackageError.invalid("Checkpoint state does not match output") }
                for event in events { try putEvent(event,preserveReviewed:true) }
                if var graph: EvidenceBundle = try metadata("evidence") {
                    let savedEvents = try self.events()
                    let tracksChanged = try appendTracks(frames.flatMap { $0.players.compactMap(\.courtPosition) })
                    if graph.events.events != savedEvents || tracksChanged {
                        graph.events.events = savedEvents
                        graph.metrics.metrics = []; graph.insights.insights = []
                        try setMetadata("evidence", graph)
                        try setMetadata("automaticTrackSampling", TrackSummaryBuilder.version)
                    }
                }
                try setMetadata("state",state); try setMetadata("status",status); try sql("COMMIT")
            } catch { try? sql("ROLLBACK"); throw error }
        }
    }
    private func putEvent(_ event:AnalysisEvent,preserveReviewed:Bool)throws {
        if preserveReviewed, let old=try eventById(event.id),old.reviewed || old.excluded || old.provenance=="manual" { return }
        try statement("INSERT INTO events(id,start,payload) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET start=excluded.start,payload=excluded.payload") { s in
            bind(event.id,to:s,at:1); sqlite3_bind_double(s,2,event.start); bind(try ContractJSON.encoder().encode(event),to:s,at:3); try done(s)
        }
    }
    private func eventById(_ id:String)throws->AnalysisEvent? {
        try statement("SELECT payload FROM events WHERE id=?") { s in
            bind(id,to:s,at:1); if sqlite3_step(s)==SQLITE_ROW { return try ContractJSON.decoder().decode(AnalysisEvent.self,from:rowData(s,column:0)) }; return nil
        }
    }
    public func saveEvent(_ event:AnalysisEvent,duration:Double)throws {
        try event.validate(duration:duration)
        try synchronized {
            guard try evidence() != nil else {
                try putEvent(event, preserveReviewed: false); return
            }
            var corrected = event
            let before = try eventById(event.id)
            if before?.position != event.position && event.position != nil { corrected.positionSource = "reviewed_bounce" }
            if before?.start != event.start && before?.contactInterval == event.contactInterval { corrected.contactInterval = nil }
            corrected.provenance = "manual"; corrected.confidence = nil; corrected.fieldConfidence = [:]
            try saveReviewedEntity(.event(corrected), duration: duration, reason: "event review")
        }
    }
    public func saveReviewedEntity(_ entity: CorrectedEntity, duration: Double,
                                   actor: String = "local-user", reason: String) throws {
        try saveReviewedEntities([entity], duration: duration, actor: actor, reason: reason)
    }
    /// Validate the final graph once, allowing assignment and participant changes to be committed together.
    /// Payloads are stored exactly as supplied; callers explicitly choose reviewed fields and provenance.
    public func saveReviewedEntities(_ entities: [CorrectedEntity], duration: Double,
                                     actor: String = "local-user", reason: String) throws {
        guard !entities.isEmpty else { return }
        try EvidenceBundle.require(duration.isFinite && duration >= 0 && !actor.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty
            && !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty, "Review needs duration, actor and reason")
        try EvidenceBundle.require(Set(entities.map { "\($0.kind):\($0.id)" }).count == entities.count,
                                   "Duplicate entity in review transaction")
        try synchronized {
            try sql("BEGIN IMMEDIATE")
            do {
                var graph = try evidenceSnapshot()
                func replace<T: Identifiable>(_ value: T, in rows: inout [T]) -> T? where T.ID == String {
                    if let offset = rows.firstIndex(where: { $0.id == value.id }) {
                        let old = rows[offset]; rows[offset] = value; return old
                    }
                    rows.append(value); return nil
                }
                for entity in entities {
                    let before: CorrectedEntity?
                    switch entity {
                    case .event(let value):
                        before = replace(value, in: &graph.events.events).map(CorrectedEntity.event)
                    case .participant(let value):
                        var rows = graph.events.participants ?? []
                        before = replace(value, in: &rows).map(CorrectedEntity.participant); graph.events.participants = rows
                    case .assignment(let value):
                        var rows = graph.events.assignments ?? []
                        before = replace(value, in: &rows).map(CorrectedEntity.assignment); graph.events.assignments = rows
                    case .link(let value):
                        var rows = graph.events.links ?? []
                        before = replace(value, in: &rows).map(CorrectedEntity.link); graph.events.links = rows
                    case .rally(let value):
                        before = replace(value, in: &graph.rallies.rallies).map(CorrectedEntity.rally)
                    }
                    if before == entity { continue }
                    graph.audit.append(EvidenceCorrection(schemaVersion: 1, id: UUID().uuidString,
                        sequence: graph.audit.count + 1, entityId: entity.id, actor: actor,
                        timestamp: ISO8601DateFormatter().string(from: Date()), reason: reason,
                        before: before, after: entity, entityType: entity.kind))
                }
                graph.events.events.sort { ($0.start, $0.id) < ($1.start, $1.id) }
                graph.metrics.metrics = []; graph.insights.insights = []
                try graph.validate(duration: duration)
                for event in graph.events.events { try putEvent(event, preserveReviewed: false) }
                try writeEvidence(graph); try sql("COMMIT")
            } catch { try? sql("ROLLBACK"); throw error }
        }
    }
    public func evidence() throws -> EvidenceBundle? { try synchronized { try readEvidence() } }
    /// Returns a value snapshot. Older stores are projected into v3 without modifying the database.
    public func evidenceSnapshot() throws -> EvidenceBundle {
        try synchronized {
            if let graph = try readEvidence() { return graph }
            var graph = EvidenceBundle.migrating(events: try events())
            graph.tracks = try framePositions()
            return graph
        }
    }
    private func framePositions() throws -> [PlayerPosition] {
        try statement("SELECT payload FROM frames ORDER BY frame") { s in
            var summary = try TrackSummaryBuilder(), code = sqlite3_step(s)
            while code == SQLITE_ROW {
                let frame = try ContractJSON.decoder().decode(FrameRecord.self, from: rowData(s, column: 0))
                for position in frame.players.compactMap(\.courtPosition) { try summary.append(position) }
                code = sqlite3_step(s)
            }
            guard code == SQLITE_DONE else { throw failure() }
            return summary.samples
        }
    }
    public func importEvidence(_ graph: EvidenceBundle, duration: Double) throws {
        try graph.validate(duration: duration)
        try synchronized {
            try sql("BEGIN IMMEDIATE")
            do {
                var graph = graph
                var summary = try TrackSummaryBuilder(existing: graph.tracks)
                for position in try framePositions() { try summary.append(position) }
                if summary.samples.count != graph.tracks.count {
                    graph.tracks = summary.samples
                    graph.metrics.metrics = []; graph.insights.insights = []
                    try setMetadata("automaticTrackSampling", TrackSummaryBuilder.version)
                }
                try graph.validate(duration: duration)
                try sql("DELETE FROM events")
                for event in graph.events.events { try putEvent(event, preserveReviewed: false) }
                try writeEvidence(graph); try sql("COMMIT")
            } catch { try? sql("ROLLBACK"); throw error }
        }
    }
    public func events()throws->[AnalysisEvent] {
        try synchronized {
            try statement("SELECT payload FROM events ORDER BY start,id") { s in
                var output=[AnalysisEvent](); var code=sqlite3_step(s)
                while code==SQLITE_ROW { output.append(try ContractJSON.decoder().decode(AnalysisEvent.self,from:rowData(s,column:0))); code=sqlite3_step(s) }
                guard code==SQLITE_DONE else { throw failure() }; return output
            }
        }
    }
    public func frame(at time:Double)throws->FrameRecord? {
        try synchronized {
            try statement("SELECT payload FROM frames WHERE timestamp<=? ORDER BY timestamp DESC LIMIT 1") { s in
                sqlite3_bind_double(s,1,time)
                if sqlite3_step(s)==SQLITE_ROW { return try ContractJSON.decoder().decode(FrameRecord.self,from:rowData(s,column:0)) }; return nil
            }
        }
    }
    public func neighboringTime(_ time:Double,forward:Bool)throws->Double? {
        try synchronized {
            let query=forward ? "SELECT timestamp FROM frames WHERE timestamp>? ORDER BY timestamp LIMIT 1" : "SELECT timestamp FROM frames WHERE timestamp<? ORDER BY timestamp DESC LIMIT 1"
            return try statement(query) { s in sqlite3_bind_double(s,1,time+(forward ? 0.00001 : -0.00001)); return sqlite3_step(s)==SQLITE_ROW ? sqlite3_column_double(s,0) : nil }
        }
    }
    public func trajectory(ending time:Double,seconds:Double=1,limit:Int=180)throws->[FrameRecord] {
        try synchronized {
            try statement("SELECT payload FROM frames WHERE timestamp BETWEEN ? AND ? ORDER BY timestamp DESC LIMIT ?") { s in
                sqlite3_bind_double(s,1,max(0,time-seconds)); sqlite3_bind_double(s,2,time); sqlite3_bind_int(s,3,Int32(max(1,min(limit,1000))))
                var output=[FrameRecord](); var code=sqlite3_step(s)
                while code==SQLITE_ROW { output.append(try ContractJSON.decoder().decode(FrameRecord.self,from:rowData(s,column:0))); code=sqlite3_step(s) }
                guard code==SQLITE_DONE else { throw failure() }; return output.reversed()
            }
        }
    }
    public func export(to root:URL,manifest:Manifest)throws {
        try manifest.validate()
        try synchronized {
            var manifest = manifest
            if manifest.schemaVersion == 3, let policy: String = try metadata("automaticTrackSampling") {
                manifest.derivationVersions?["automatic_track_sampling"] = policy
            }
            let target=try PackageIO.asset(manifest.artifacts["frames"]!,in:root)
            let temporary=target.appendingPathExtension("pending")
            FileManager.default.createFile(atPath:temporary.path,contents:nil)
            do {
                let handle=try FileHandle(forWritingTo:temporary); defer { try? handle.close() }
                try statement("SELECT payload FROM frames ORDER BY frame") { s in
                    var code=sqlite3_step(s)
                    while code==SQLITE_ROW { try handle.write(contentsOf:rowData(s,column:0)); try handle.write(contentsOf:Data([10])); code=sqlite3_step(s) }
                    guard code==SQLITE_DONE else { throw failure() }
                }
                try handle.synchronize(); try handle.close()
                if FileManager.default.fileExists(atPath:target.path) { _ = try FileManager.default.replaceItemAt(target,withItemAt:temporary) }
                else { try FileManager.default.moveItem(at:temporary,to:target) }
                if manifest.schemaVersion == 3 {
                    let graph = try evidenceSnapshot()
                    try graph.write(to: root, manifest: manifest)
                } else {
                    guard try evidence() == nil else { throw PackageError.invalid("Cannot downgrade v3 evidence to v2") }
                    try ContractJSON.write(EventCollection(events:events()),to:PackageIO.asset(manifest.artifacts["events"]!,in:root))
                }
                try ContractJSON.write(corrections(),to:PackageIO.asset(manifest.artifacts["corrections"]!,in:root))
                try ContractJSON.write(manifest,to:root.appendingPathComponent("manifest.json"))
            } catch { try? FileManager.default.removeItem(at:temporary); throw error }
        }
    }
    /// Imports validated JSONL incrementally; original package remains untouched.
    public func importFrames(from url:URL)throws {
        var current=try state(); var batch=[FrameRecord]()
        try PackageIO.readFrames(url) { frame in
            guard frame.frame>=current.nextFrame else { return }
            batch.append(frame); current.nextFrame=frame.frame+1; current.lastTimestamp=frame.timestamp
            if batch.count>=120 { try checkpoint(frames:batch,events:[],state:current,status:.complete); batch=[] }
        }
        if !batch.isEmpty { try checkpoint(frames:batch,events:[],state:current,status:.complete) }
    }
}
