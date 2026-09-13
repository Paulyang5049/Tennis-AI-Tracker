import Foundation

public struct PackageMigration: Codable, Equatable, Sendable {
    public var fromVersion: Int
    public var sourceMediaSha256: String
    public var method: String
}
public struct Participant: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var name: String; public var role: String
}
public struct SceneRoleAssignment: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var scene: Int; public var start: Double; public var end: Double
    public var trackId: Int; public var side: String; public var participantId: String?
    public var reviewed: Bool; public var confidence: Double?
}
public struct ShotBounceLink: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var shotId: String; public var bounceId: String
    public var reviewed: Bool; public var confidence: Double?
}
public struct RallyEvidence: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var start: Double; public var end: Double
    public var shotIds: [String]; public var reviewed: Bool; public var outcome: String?
}
public struct EvidenceMetric: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var definition: String; public var version: String; public var view: String
    public var value: Double?; public var numerator: Double; public var denominator: Double
    public var eventIds: [String]; public var excludedEventIds: [String]
    public var inputDigest: String; public var reviewPolicyVersion: String
}
public struct CoachingInsight: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var observation: String; public var interpretation: String; public var action: String
    public var metricIds: [String]; public var eventIds: [String]; public var confidence: String; public var ruleVersion: String
}
public struct PlayerPosition: Codable, Equatable, Sendable {
    public var schemaVersion: Int; public var timestamp: Double; public var scene: Int; public var trackId: Int
    public var side: String; public var positionCourtM: [Double]?; public var method: String?
    public var reviewed: Bool; public var calibrationId: String?
    public var imagePointPx: [Double]? = nil; public var errorM: Double? = nil; public var roleState: String? = nil
}
public enum CorrectedEntity: Codable, Equatable, Sendable {
    case event(AnalysisEvent), assignment(SceneRoleAssignment), participant(Participant), rally(RallyEvidence)
    public var id: String {
        switch self { case .event(let x): return x.id; case .assignment(let x): return x.id
        case .participant(let x): return x.id; case .rally(let x): return x.id }
    }
    public var kind: String {
        switch self { case .event: return "event"; case .assignment: return "assignment"
        case .participant: return "participant"; case .rally: return "rally" }
    }
    public var event: AnalysisEvent? { if case .event(let value) = self { return value }; return nil }
    public init(from decoder: Decoder) throws {
        let container = try decoder.singleValueContainer()
        if let value = try? container.decode(AnalysisEvent.self) { self = .event(value) }
        else if let value = try? container.decode(SceneRoleAssignment.self) { self = .assignment(value) }
        else if let value = try? container.decode(Participant.self) { self = .participant(value) }
        else { self = .rally(try container.decode(RallyEvidence.self)) }
    }
    public func encode(to encoder: Encoder) throws {
        switch self { case .event(let x): try x.encode(to: encoder); case .assignment(let x): try x.encode(to: encoder)
        case .participant(let x): try x.encode(to: encoder); case .rally(let x): try x.encode(to: encoder) }
    }
}
public struct EvidenceCorrection: Codable, Equatable, Identifiable, Sendable {
    public var schemaVersion: Int; public var id: String; public var sequence: Int; public var entityId: String
    public var actor: String; public var timestamp: String; public var reason: String
    public var before: CorrectedEntity?; public var after: CorrectedEntity
    public var entityType: String? = nil
}
public struct RallyCollection: Codable, Equatable, Sendable {
    public var schemaVersion = 1; public var rallies: [RallyEvidence] = []
}
public struct MetricCollection: Codable, Equatable, Sendable {
    public var schemaVersion = 1; public var metrics: [EvidenceMetric] = []
}
public struct InsightCollection: Codable, Equatable, Sendable {
    public var schemaVersion = 1; public var insights: [CoachingInsight] = []
}

/// Separate, bounded assets keep observations, human corrections and derived claims distinct.
public struct EvidenceBundle: Codable, Equatable, Sendable {
    public static let assetVersions = ["frames": 2, "events": 3, "corrections": 2, "tracks": 1,
                                      "rallies": 1, "metrics": 1, "insights": 1, "audit": 1]
    public static let extraAssets = ["tracks": "tracks.jsonl", "rallies": "rallies.json",
                                    "metrics": "metrics.json", "insights": "insights.json", "audit": "corrections.jsonl"]
    public static let maxBytes = 32 * 1024 * 1024
    public static let maxRows = 100_000
    public var events: EventCollection
    public var rallies = RallyCollection(); public var metrics = MetricCollection(); public var insights = InsightCollection()
    public var tracks: [PlayerPosition] = []; public var audit: [EvidenceCorrection] = []

    public init(events: EventCollection) { self.events = events }
    public static func migrating(events: [AnalysisEvent]) -> EvidenceBundle {
        var document = EventCollection(events: events.map { event in
            var copy = event
            if copy.position != nil { copy.positionSource = "legacy_v2" }
            return copy
        })
        document.schemaVersion = 3; document.participants = []; document.assignments = []; document.links = []
        return EvidenceBundle(events: document)
    }

    static func require(_ valid: Bool, _ message: String) throws {
        guard valid else { throw PackageError.invalid(message) }
    }
    static func index<T: Identifiable>(_ rows: [T]) throws -> [String: T] where T.ID == String {
        try require(rows.count <= maxRows, "Evidence collection exceeds row limit")
        var result: [String: T] = [:]
        for row in rows {
            try require(!row.id.isEmpty && result[row.id] == nil, "Evidence IDs must be nonempty and unique")
            result[row.id] = row
        }
        return result
    }
    static func point(_ value: [Double]?) throws {
        if let value { try require(value.count == 2 && value.allSatisfy(\.isFinite), "Invalid evidence point") }
    }
    static func confidence(_ value: Double?) throws {
        if let value { try require(value.isFinite && (0...1).contains(value), "Invalid confidence") }
    }
    static func interval(_ start: Double, _ end: Double, _ duration: Double) throws {
        try require(start.isFinite && end.isFinite && start >= 0 && start <= end && end <= duration, "Invalid evidence temporal order or duration")
    }
    static func references<T>(_ ids: [String], _ lookup: [String: T]) throws {
        try require(Set(ids).count == ids.count && ids.allSatisfy({ lookup[$0] != nil }), "Broken or duplicate evidence reference")
    }
    public func validate(duration: Double) throws {
        try Self.require(events.schemaVersion == 3 && events.participants != nil && events.assignments != nil && events.links != nil, "Invalid v3 event collection")
        let eventIndex = try Self.index(events.events), people = try Self.index(events.participants!)
        let assignments = Array(try Self.index(events.assignments!).values)
        _ = try Self.index(events.links!)
        for person in people.values { try Self.require(["self", "opponent", "partner", "unknown"].contains(person.role), "Unsupported participant role") }
        for assignment in assignments {
            try Self.interval(assignment.start, assignment.end, duration); try Self.confidence(assignment.confidence)
            try Self.require(assignment.scene >= 0 && ["near", "far"].contains(assignment.side), "Invalid side assignment")
            if let id = assignment.participantId { try Self.require(people[id] != nil, "Broken participant reference") }
            try Self.require(!assignment.reviewed || assignment.participantId != nil, "Reviewed assignment needs a participant")
        }
        // Sort once per track, avoiding quadratic work on imported match-long assignments.
        let grouped = Dictionary(grouping: assignments) { "\($0.scene):\($0.trackId)" }
        for group in grouped.values {
            let ordered = group.sorted { $0.start < $1.start }
            for i in ordered.indices.dropFirst() {
                try Self.require(ordered[i-1].end <= ordered[i].start, "Overlapping track assignment intervals")
            }
        }
        for event in events.events {
            try event.validate(duration: duration); try Self.interval(event.start, event.end, duration)
            try Self.point(event.contactPointImagePx); try Self.point(event.hitterPositionCourtM); try Self.point(event.contactInterval)
            if let range = event.contactInterval {
                try Self.require(event.kind == .hit && range[0] >= 0 && range[0] <= event.start && event.start <= range[1] && range[1] <= duration, "Invalid contact interval")
            }
            try Self.require(event.kind == .hit || (event.contactPointImagePx == nil && event.hitterPositionCourtM == nil), "Contact observations belong to hit events")
            for value in (event.fieldConfidence ?? [:]).values { try Self.confidence(value) }
            if event.position != nil { try Self.require(["reviewed_bounce", "legacy_v2"].contains(event.positionSource ?? ""), "Landing requires bounce provenance") }
            if let id = event.participantId {
                try Self.require(people[id] != nil, "Broken participant reference")
                let matches = assignments.filter { $0.scene == event.scene && $0.trackId == event.playerId && $0.start <= event.start && event.start < $0.end && $0.participantId == id }
                try Self.require(matches.count == 1 && (!event.reviewed || matches.first?.reviewed == true), "Participant event requires an unambiguous matching assignment")
            }
        }
        for link in events.links! {
            try Self.references([link.shotId, link.bounceId], eventIndex)
            let hit = eventIndex[link.shotId]!, bounce = eventIndex[link.bounceId]!
            try Self.require(hit.kind == .hit && bounce.kind == .bounce && hit.scene == bounce.scene && hit.start <= bounce.start, "Invalid shot-bounce association")
            try Self.confidence(link.confidence)
            try Self.require(!link.reviewed || (hit.reviewed && bounce.reviewed), "Reviewed link requires reviewed events")
        }
        try Self.require(rallies.schemaVersion == 1 && metrics.schemaVersion == 1 && insights.schemaVersion == 1, "Unsupported derived asset version")
        _ = try Self.index(rallies.rallies); let metricIndex = try Self.index(metrics.metrics); _ = try Self.index(insights.insights)
        for rally in rallies.rallies {
            try Self.interval(rally.start, rally.end, duration); try Self.references(rally.shotIds, eventIndex)
            let shots = rally.shotIds.map { eventIndex[$0]! }, times = shots.map(\.start)
            try Self.require(times == times.sorted() && shots.allSatisfy { $0.kind == .hit && $0.start >= rally.start && $0.start <= rally.end }, "Rally shots must be ordered contained hits")
            try Self.require(rally.outcome == nil || ["self_won", "opponent_won", "unknown"].contains(rally.outcome!), "Invalid rally outcome")
        }
        for metric in metrics.metrics {
            try Self.references(metric.eventIds, eventIndex); try Self.references(metric.excludedEventIds, eventIndex)
            try Self.require(metric.value?.isFinite ?? true, "Invalid metric value")
            try Self.require(metric.numerator.isFinite && metric.denominator.isFinite && metric.numerator >= 0 && metric.numerator <= metric.denominator, "Invalid metric counts")
            try Self.require(["human_verified", "assisted"].contains(metric.view) && !metric.inputDigest.isEmpty && metric.reviewPolicyVersion == "human-reviewed-v1", "Metric needs view and input provenance")
            if metric.view == "human_verified" {
                try Self.require(metric.eventIds.allSatisfy { eventIndex[$0]!.reviewed && !eventIndex[$0]!.excluded }, "Verified metric cannot use candidate or excluded evidence")
            }
        }
        for insight in insights.insights {
            try Self.references(insight.metricIds, metricIndex); try Self.references(insight.eventIds, eventIndex)
            try Self.require(!insight.metricIds.isEmpty && !insight.eventIds.isEmpty && insight.metricIds.allSatisfy { metricIndex[$0]!.view == "human_verified" }, "Coaching requires human-verified supporting metrics")
            let supported = Set(insight.metricIds.flatMap { metricIndex[$0]!.eventIds })
            try Self.require(Set(insight.eventIds).isSubset(of: supported), "Insight evidence must support its metrics")
            try Self.require(["limited", "moderate"].contains(insight.confidence), "Invalid insight confidence")
        }
        _ = try Self.index(audit)
        for (i, record) in audit.enumerated() {
            let exists: Bool
            switch record.after {
            case .event: exists = eventIndex[record.entityId] != nil
            case .participant: exists = people[record.entityId] != nil
            case .assignment: exists = assignments.contains { $0.id == record.entityId }
            case .rally: exists = rallies.rallies.contains { $0.id == record.entityId }
            }
            try Self.require(record.schemaVersion == 1 && record.sequence == i + 1 && exists, "Invalid append-only audit sequence or entity")
            try Self.require((record.entityType ?? "event") == record.after.kind && (record.before == nil || (record.before?.kind == record.after.kind && record.before?.id == record.entityId)), "Audit entity type mismatch")
            try Self.require(!record.actor.isEmpty && !record.reason.isEmpty && !record.timestamp.isEmpty && record.after.id == record.entityId, "Audit requires actor, reason, timestamp and matching entity")
        }
        try Self.require(tracks.count <= Self.maxRows, "Track collection exceeds row limit")
        for sample in tracks {
            try Self.require(sample.schemaVersion == 1 && sample.timestamp.isFinite && sample.timestamp >= 0 && sample.timestamp <= duration && sample.scene >= 0 && ["near", "far", "unknown"].contains(sample.side), "Invalid track time, side or version")
            try Self.point(sample.positionCourtM)
            try Self.point(sample.imagePointPx)
            if let error = sample.errorM { try Self.require(error.isFinite && error >= 0, "Invalid position error") }
            if let state = sample.roleState { try Self.require(["candidate", "unknown", "ambiguous"].contains(state), "Invalid role state") }
            if sample.positionCourtM != nil { try Self.require(["ankles_homography", "box_bottom_homography"].contains(sample.method ?? "") && !(sample.calibrationId ?? "").isEmpty, "Player position needs ground-point method and calibration") }
        }
    }
    static func boundedData(_ url: URL) throws -> Data {
        let size = (try url.resourceValues(forKeys: [.fileSizeKey])).fileSize ?? 0
        try require(size <= maxBytes, "Evidence asset exceeds size limit")
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        let data = try handle.read(upToCount: maxBytes + 1) ?? Data()
        try require(data.count <= maxBytes, "Evidence asset exceeds size limit")
        return data
    }
    public static func boundedImportData(_ url: URL) throws -> Data { try boundedData(url) }
    static func read<T: Decodable>(_ type: T.Type, _ url: URL) throws -> T {
        try ContractJSON.decoder().decode(type, from: boundedData(url))
    }
    static func readLines<T: Decodable>(_ type: T.Type, _ url: URL) throws -> [T] {
        let data = try boundedData(url), lines = data.split(separator: 10).filter { !$0.allSatisfy { [9, 13, 32].contains($0) } }
        try require(lines.count <= maxRows, "Evidence asset exceeds row limit")
        return try lines.map { try ContractJSON.decoder().decode(type, from: Data($0)) }
    }
    public static func load(_ root: URL, manifest provided: Manifest? = nil) throws -> EvidenceBundle {
        let manifest = try provided ?? PackageIO.load(root)
        try require(manifest.schemaVersion == 3, "Expected v3 evidence package")
        func asset(_ key: String) throws -> URL { guard let path = manifest.artifacts[key] else { throw PackageError.invalid("Missing evidence asset") }; return try PackageIO.asset(path, in: root) }
        var bundle = EvidenceBundle(events: try read(EventCollection.self, asset("events")))
        bundle.rallies = try read(RallyCollection.self, asset("rallies"))
        bundle.metrics = try read(MetricCollection.self, asset("metrics"))
        bundle.insights = try read(InsightCollection.self, asset("insights"))
        bundle.tracks = try readLines(PlayerPosition.self, asset("tracks"))
        bundle.audit = try readLines(EvidenceCorrection.self, asset("audit"))
        var events = try index(bundle.events.events)
        let original = events
        let originalPeople = bundle.events.participants, originalAssignments = bundle.events.assignments
        let originalRallies = bundle.rallies
        var people = bundle.events.participants ?? [], assignments = bundle.events.assignments ?? []
        var rallies = bundle.rallies.rallies
        _ = try index(people); _ = try index(assignments); _ = try index(rallies)
        var peopleIndex = Dictionary(uniqueKeysWithValues: people.enumerated().map { ($0.element.id, $0.offset) })
        var assignmentIndex = Dictionary(uniqueKeysWithValues: assignments.enumerated().map { ($0.element.id, $0.offset) })
        var rallyIndex = Dictionary(uniqueKeysWithValues: rallies.enumerated().map { ($0.element.id, $0.offset) })
        func replace<T: Identifiable>(_ value: T, rows: inout [T], positions: inout [String: Int]) where T.ID == String {
            if let offset = positions[value.id] { rows[offset] = value }
            else { positions[value.id] = rows.count; rows.append(value) }
        }
        for record in bundle.audit {
            switch record.after {
            case .event(let value): events[record.entityId] = value
            case .participant(let value):
                replace(value, rows: &people, positions: &peopleIndex)
            case .assignment(let value):
                replace(value, rows: &assignments, positions: &assignmentIndex)
            case .rally(let value):
                replace(value, rows: &rallies, positions: &rallyIndex)
            }
        }
        if bundle.events.participants != nil { bundle.events.participants = people }
        if bundle.events.assignments != nil { bundle.events.assignments = assignments }
        bundle.rallies.rallies = rallies
        if events != original || bundle.events.participants != originalPeople || bundle.events.assignments != originalAssignments || bundle.rallies != originalRallies { bundle.metrics.metrics = []; bundle.insights.insights = [] }
        bundle.events.events = events.values.sorted { ($0.start, $0.id) < ($1.start, $1.id) }
        try bundle.validate(duration: manifest.media.duration)
        return bundle
    }
    public func write(to root: URL, manifest: Manifest) throws {
        try validate(duration: manifest.media.duration)
        func asset(_ key: String) throws -> URL { guard let path = manifest.artifacts[key] else { throw PackageError.invalid("Missing evidence asset") }; return try PackageIO.asset(path, in: root) }
        try ContractJSON.write(events, to: asset("events")); try ContractJSON.write(rallies, to: asset("rallies"))
        try ContractJSON.write(metrics, to: asset("metrics")); try ContractJSON.write(insights, to: asset("insights"))
        func writeLines<T: Encodable>(_ values: [T], _ path: URL) throws {
            var data = Data()
            for value in values { data.append(try ContractJSON.encoder().encode(value)); data.append(10) }
            try data.write(to: path, options: .atomic)
        }
        try writeLines(tracks, asset("tracks")); try writeLines(audit, asset("audit"))
    }
}

extension Manifest {
    public func migratedToV3() throws -> Manifest {
        try validate()
        if schemaVersion == 3 { return self }
        var copy = self
        copy.schemaVersion = 3; copy.assetVersions = EvidenceBundle.assetVersions
        copy.courtCoordinateSystem = "far_left_x_right_y_near_m"
        copy.reviewPolicyVersion = "human-reviewed-v1"; copy.derivationVersions = [:]
        copy.storagePolicy = "local-no-backup-explicit-export"
        copy.artifacts.merge(EvidenceBundle.extraAssets) { _, new in new }
        copy.migration = PackageMigration(fromVersion: 2, sourceMediaSha256: media.sha256, method: "additive-v1")
        return copy
    }
}
