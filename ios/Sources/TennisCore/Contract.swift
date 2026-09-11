import Foundation

public enum PackageError: Error, LocalizedError {
    case unsupportedVersion(Int), invalid(String), incompatibleResume, database(String)
    public var errorDescription: String? {
        switch self {
        case .unsupportedVersion(let n): return "Unsupported analysis schema: \(n)"
        case .invalid(let reason): return reason
        case .incompatibleResume: return "Media, model, settings or runtime changed. Start a new analysis."
        case .database(let reason): return "Analysis database: \(reason)"
        }
    }
}

public enum ContractJSON {
    public static func encoder() -> JSONEncoder {
        let e = JSONEncoder(); e.keyEncodingStrategy = .convertToSnakeCase
        e.outputFormatting = [.sortedKeys]; return e
    }
    public static func decoder() -> JSONDecoder {
        let d = JSONDecoder(); d.keyDecodingStrategy = .convertFromSnakeCase; return d
    }
    public static func read<T: Decodable>(_ type: T.Type, from url: URL) throws -> T {
        try decoder().decode(type, from: Data(contentsOf: url))
    }
    public static func write<T: Encodable>(_ value: T, to url: URL) throws {
        try encoder().encode(value).write(to: url, options: .atomic)
    }
}

public struct Media: Codable, Equatable, Sendable {
    public var id: String; public var sha256: String; public var path: String
    public var width: Int; public var height: Int; public var duration: Double; public var origin: Double
    public var fps: Double?; public var rotation: Double?; public var hasAudio: Bool?
    public init(id: String, path: String, width: Int, height: Int, duration: Double, origin: Double = 0, fps: Double? = nil, hasAudio: Bool? = nil) {
        self.id = id; sha256 = id; self.path = path; self.width = width; self.height = height
        self.duration = duration; self.origin = origin; self.fps = fps; self.hasAudio = hasAudio
    }
}
public struct AnalysisSettings: Codable, Equatable, Sendable {
    public var players: Int
    public init(players: Int = 2) { self.players = players }
}
public enum AnalysisStatus: String, Codable, Sendable {
    case running, paused, cancelled, failed, inferenceComplete = "inference_complete", complete
}
public struct Manifest: Codable, Equatable, Sendable {
    public var schemaVersion: Int = 2
    public var media: Media; public var settings: AnalysisSettings; public var modelProvenance: [String: String]
    public var status: AnalysisStatus; public var coordinateSystem = "oriented_pixels_top_left"
    public var artifacts = ["frames": "frames.jsonl", "events": "events.json", "corrections": "corrections.json"]
    public var assetVersions: [String: Int]?
    public var courtCoordinateSystem: String?
    public var reviewPolicyVersion: String?
    public var derivationVersions: [String: String]?
    public var storagePolicy: String?
    public var migration: PackageMigration?
    public init(media: Media, settings: AnalysisSettings = .init(), modelProvenance: [String: String] = [:], status: AnalysisStatus = .paused) {
        self.media = media; self.settings = settings; self.modelProvenance = modelProvenance; self.status = status
    }
    public func validate() throws {
        guard [2, 3].contains(schemaVersion) else { throw PackageError.unsupportedVersion(schemaVersion) }
        if schemaVersion == 3 {
            guard assetVersions == EvidenceBundle.assetVersions,
                  courtCoordinateSystem == "far_left_x_right_y_near_m",
                  reviewPolicyVersion == "human-reviewed-v1", derivationVersions != nil,
                  storagePolicy == "local-no-backup-explicit-export",
                  EvidenceBundle.assetVersions.keys.allSatisfy({ artifacts[$0] != nil }) else {
                throw PackageError.invalid("Invalid v3 versions, storage or review policy")
            }
        }
        guard [2,4].contains(settings.players), media.width > 0, media.height > 0,
              media.duration.isFinite, media.duration > 0, media.origin.isFinite,
              !media.id.isEmpty, !media.sha256.isEmpty,
              coordinateSystem == "oriented_pixels_top_left",
              ["frames", "events", "corrections"].allSatisfy({ artifacts[$0] != nil }) else {
            throw PackageError.invalid("Invalid media, settings or coordinate system")
        }
    }
}
public struct Detection: Codable, Equatable, Sendable {
    public var box: [Double]; public var confidence: Double; public var playerId: Int?
    public init(box: [Double], confidence: Double) { self.box = box; self.confidence = confidence }
    public var center: [Double] { [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2] }
}
public struct Player: Codable, Equatable, Sendable {
    public var id: Int; public var box: [Double]; public var confidence: Double; public var label: String?; public var pose: [[Double]]?
    public init(id: Int, box: [Double], confidence: Double) { self.id = id; self.box = box; self.confidence = confidence }
}
public struct Ball: Codable, Equatable, Sendable {
    public enum Status: String, Codable, Sendable { case observed, interpolated, missing }
    public var status: Status; public var xy: [Double]?; public var confidence: Double?
    public init(status: Status = .missing, xy: [Double]? = nil, confidence: Double? = nil) {
        self.status = status; self.xy = xy; self.confidence = confidence
    }
}
public struct Court: Codable, Equatable, Sendable {
    public var matrix: [[Double]]; public var points: [[Double]]; public var source: String
    public init(points: [[Double]]) throws {
        self.points = points; matrix = try Homography.solve(points: points); source = "manual"
    }
}
public struct FrameRecord: Codable, Equatable, Sendable {
    public var schemaVersion = 2; public var frame: Int; public var timestamp: Double
    public var scene = 0; public var cut = false; public var cameraMoving = false
    public var court: Court?; public var players: [Player] = []; public var rackets: [Detection] = []
    public var ballCandidates: [Detection] = []; public var ball = Ball()
    public init(frame: Int, timestamp: Double, players: [Player] = [], ball: Ball = .init()) {
        self.frame = frame; self.timestamp = timestamp; self.players = players; self.ball = ball
    }
    public func validate() throws {
        guard [1,2].contains(schemaVersion) else { throw PackageError.unsupportedVersion(schemaVersion) }
        guard frame >= 0, timestamp.isFinite, timestamp >= 0 else { throw PackageError.invalid("Invalid frame timestamp") }
        for box in players.map(\.box) + rackets.map(\.box) + ballCandidates.map(\.box) {
            guard box.count == 4, box.allSatisfy(\.isFinite), box[2] >= box[0], box[3] >= box[1] else { throw PackageError.invalid("Invalid box") }
        }
        if let xy = ball.xy { guard xy.count == 2, xy.allSatisfy(\.isFinite) else { throw PackageError.invalid("Invalid ball point") } }
        guard (ball.status == .missing) == (ball.xy == nil) else { throw PackageError.invalid("Ball status and coordinates disagree") }
    }
}
public enum EventKind: String, Codable, CaseIterable, Sendable { case hit, bounce, rally }
public enum Stroke: String, Codable, CaseIterable, Sendable { case serve, forehand, backhand, volley, overhead, unknown }
public struct AnalysisEvent: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var kind: EventKind; public var start: Double; public var end: Double
    public var scene: Int = 0; public var playerId: Int?; public var stroke: Stroke = .unknown
    public var position: [Double]?; public var provenance = "manual"; public var reviewed = true
    public var confidence: Double?; public var excluded = false; public var favorite = false
    public var participantId: String?
    public var contactInterval: [Double]?
    public var contactPointImagePx: [Double]?
    public var hitterPositionCourtM: [Double]?
    public var fieldConfidence: [String: Double?]?
    public var positionSource: String?
    public init(id: String = UUID().uuidString, kind: EventKind, start: Double, end: Double? = nil) {
        self.id = id; self.kind = kind; self.start = start; self.end = end ?? start
    }
    public func validate(duration: Double) throws {
        guard !id.isEmpty, start.isFinite, end.isFinite, start >= 0, end >= start, end <= duration + 0.001,
              kind == .rally || start == end, ["manual", "automatic"].contains(provenance) else {
            throw PackageError.invalid("Invalid event time or provenance")
        }
        if let p = position { guard kind == .bounce, p.count == 2, p.allSatisfy(\.isFinite) else { throw PackageError.invalid("Invalid court position") } }
        if let c = confidence { guard c.isFinite, (0...1).contains(c) else { throw PackageError.invalid("Invalid confidence") } }
    }
}
public struct EventCollection: Codable, Equatable, Sendable {
    public var schemaVersion = 2; public var events: [AnalysisEvent]
    public var participants: [Participant]?
    public var assignments: [SceneRoleAssignment]?
    public var links: [ShotBounceLink]?
    public init(events: [AnalysisEvent] = []) { self.events = events }
}
public struct Corrections: Codable, Equatable, Sendable {
    public var court: [String: [[Double]]] = [:]; public var labels: [String: [String: String]] = [:]
    public init() {}
    /// Keys follow the shared contract: absolute frame indices, not scene IDs.
    public func latestCourt(at frame:Int)throws->Court? {
        guard let key=court.keys.compactMap(Int.init).filter({ $0 <= frame }).max(),
              let points=court[String(key)] else { return nil }
        return try Court(points:points)
    }
}
public struct VerifiedStatistics: Sendable {
    public var hits: Int; public var bounces: Int; public var rallies: Int
    public var strokes: [Stroke: Int]; public var landingEvents: [AnalysisEvent]
    public init(events: [AnalysisEvent]) {
        let verified = events.filter { !$0.excluded && $0.reviewed }
        hits = verified.filter { $0.kind == .hit }.count; bounces = verified.filter { $0.kind == .bounce }.count
        rallies = verified.filter { $0.kind == .rally }.count; strokes = [:]
        for event in verified where event.kind == .hit { strokes[event.stroke, default: 0] += 1 }
        landingEvents = verified.filter { $0.kind == .bounce && $0.reviewed && $0.position != nil }
    }
}
public enum PackageIO {
    public static func asset(_ name: String, in root: URL) throws -> URL {
        guard !name.isEmpty, !name.hasPrefix("/"), !name.contains("\\"), !name.split(separator: "/").contains("..") else {
            throw PackageError.invalid("Package assets must use contained relative paths")
        }
        let base = root.resolvingSymlinksInPath().standardizedFileURL
        // Resolve each ancestor: Foundation may leave an intermediate symlink
        // unresolved when the final file does not exist yet (e.g. an export).
        var target = base
        for component in name.split(separator: "/") {
            target = target.appendingPathComponent(String(component)).resolvingSymlinksInPath().standardizedFileURL
            guard target.path.hasPrefix(base.path + "/") else { throw PackageError.invalid("Package asset escapes its folder") }
        }
        return target
    }
    public static func load(_ root: URL) throws -> Manifest {
        let url = root.appendingPathComponent("manifest.json")
        let manifest: Manifest
        if FileManager.default.fileExists(atPath: url.path) { manifest = try ContractJSON.read(Manifest.self, from: url) }
        else { manifest = try legacy(root) }
        try manifest.validate(); _ = try asset(manifest.media.path, in: root)
        let paths = try manifest.artifacts.values.map { try asset($0, in: root) }
        let reserved = [try asset(manifest.media.path, in: root), root.appendingPathComponent("manifest.json").resolvingSymlinksInPath()]
        guard Set(paths).count == paths.count, Set(paths).isDisjoint(with: reserved) else { throw PackageError.invalid("Package assets must be distinct from media and manifest") }
        return manifest
    }
    private static func legacy(_ root: URL) throws -> Manifest {
        let data = try Data(contentsOf: root.appendingPathComponent("summary.json"))
        guard let value = try JSONSerialization.jsonObject(with: data) as? [String: Any] else { throw PackageError.invalid("Invalid v1 summary") }
        let version = value["schema_version"] as? Int ?? 1
        guard version == 1 else { throw PackageError.unsupportedVersion(version) }
        guard let source = value["source"] as? String, let digest = value["source_sha256"] as? String,
              let video = value["video"] as? [String: Any], let w = video["width"] as? Int, let h = video["height"] as? Int,
              let duration = video["duration"] as? Double else { throw PackageError.invalid("Invalid v1 media") }
        let sourceURL = source.hasPrefix("/") ? URL(fileURLWithPath: source) : root.appendingPathComponent(source)
        guard sourceURL.resolvingSymlinksInPath().deletingLastPathComponent() == root.resolvingSymlinksInPath() else {
            throw PackageError.invalid("Legacy media is external; export a portable package on desktop first")
        }
        let settings = value["settings"] as? [String: Any] ?? [:]
        return Manifest(media: .init(id: digest, path: sourceURL.lastPathComponent, width: w, height: h, duration: duration,
                                    origin: video["origin"] as? Double ?? 0, fps: video["fps"] as? Double),
                        settings: .init(players: settings["players"] as? Int ?? 2), modelProvenance: value["versions"] as? [String: String] ?? [:],
                        status: AnalysisStatus(rawValue: value["status"] as? String ?? "complete") ?? .complete)
    }
    /// Streaming bounded-memory reader, also used for importing desktop packages.
    public static func readFrames(_ url: URL, consume: (FrameRecord) throws -> Void) throws {
        let handle = try FileHandle(forReadingFrom: url); defer { try? handle.close() }
        var buffer = Data()
        while let chunk = try handle.read(upToCount: 65536), !chunk.isEmpty {
            buffer.append(chunk)
            while let newline = buffer.firstIndex(of: 10) {
                let line = Data(buffer[..<newline]); buffer.removeSubrange(...newline)
                if !line.isEmpty { let frame = try ContractJSON.decoder().decode(FrameRecord.self, from: line); try frame.validate(); try consume(frame) }
            }
            guard buffer.count < 16_777_216 else { throw PackageError.invalid("Frame record exceeds size limit") }
        }
        if !buffer.isEmpty { let frame = try ContractJSON.decoder().decode(FrameRecord.self, from: buffer); try frame.validate(); try consume(frame) }
    }
}
