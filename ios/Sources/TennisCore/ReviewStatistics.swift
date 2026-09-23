import Foundation
import CryptoKit
import CoreFoundation

public enum EvidenceView: String, Codable, CaseIterable, Sendable { case assisted, humanVerified = "human_verified" }
private struct ParticipantResolver {
    let people: Set<String>
    let assignments: [String: [SceneRoleAssignment]]
    init(_ bundle: EvidenceBundle) {
        people = Set((bundle.events.participants ?? []).map(\.id))
        assignments = Dictionary(grouping: bundle.events.assignments ?? [], by: { "\($0.scene):\($0.trackId)" })
    }
    func resolve(scene: Int, track: Int?, time: Double) -> String? {
        guard let track else { return nil }
        let rows = (assignments["\(scene):\(track)"] ?? []).filter { $0.start <= time && time < $0.end }
        guard rows.count == 1, rows[0].reviewed, let pid = rows[0].participantId, people.contains(pid) else { return nil }
        return pid
    }
}
public struct ReviewPoint: Codable, Equatable, Sendable {
    public var reference: String; public var timestamp: Double; public var position: [Double]; public var participantId: String?
    enum CodingKeys: String, CodingKey { case reference, timestamp, position, participantId }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(reference, forKey: .reference); try c.encode(timestamp, forKey: .timestamp)
        try c.encode(position, forKey: .position); try c.encode(participantId, forKey: .participantId)
    }
}
public struct ReviewMetric: Codable, Equatable, Identifiable, Sendable {
    public var id: String; public var value: Double?; public var sampleCount: Int
    public var eventIds: [String]; public var supportRefs: [String]; public var exclusions: [String: String]; public var points: [ReviewPoint]
    enum CodingKeys: String, CodingKey { case id, value, sampleCount, eventIds, supportRefs, exclusions, points }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(id, forKey: .id); try c.encode(value, forKey: .value); try c.encode(sampleCount, forKey: .sampleCount)
        try c.encode(eventIds, forKey: .eventIds); try c.encode(supportRefs, forKey: .supportRefs)
        try c.encode(exclusions, forKey: .exclusions); try c.encode(points, forKey: .points)
    }
}

/// Calculated from one snapshot. Never uses a stored derived metric as current truth.
public struct ReviewReport: Codable, Equatable, Sendable {
    public var schemaVersion = 1; public var definitionVersion = "review-loop-v1"
    public var view: EvidenceView; public var participantId: String?; public var start: Double; public var end: Double
    public var inputDigest: String; public var metrics: [ReviewMetric]
    enum CodingKeys: String, CodingKey { case schemaVersion, definitionVersion, view, participantId, start, end, inputDigest, metrics }
    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(schemaVersion, forKey: .schemaVersion); try c.encode(definitionVersion, forKey: .definitionVersion)
        try c.encode(view, forKey: .view); try c.encode(participantId, forKey: .participantId)
        try c.encode(start, forKey: .start); try c.encode(end, forKey: .end)
        try c.encode(inputDigest, forKey: .inputDigest); try c.encode(metrics, forKey: .metrics)
    }

    public init(bundle: EvidenceBundle, view: EvidenceView = .assisted, participantId: String? = nil, start: Double = 0, end: Double) throws {
        guard start.isFinite, end.isFinite, start >= 0, start <= end else { throw PackageError.invalid("Invalid report time range") }
        self.view = view; self.participantId = participantId; self.start = start; self.end = end
        let data = try ContractJSON.encoder().encode(bundle)
        let object = try JSONSerialization.jsonObject(with: data) as! [String: Any]
        let source = object.filter { ["events", "rallies", "tracks", "audit"].contains($0.key) }
        let canonical = try JSONSerialization.data(withJSONObject: Self.canonical(source), options: [.sortedKeys, .withoutEscapingSlashes])
        inputDigest = SHA256.hash(data: canonical).map { String(format: "%02x", $0) }.joined()
        let verified = view == .humanVerified
        let events = Dictionary(uniqueKeysWithValues: bundle.events.events.map { ($0.id, $0) })
        let resolver = ParticipantResolver(bundle)
        let linksByBounce = Dictionary(grouping: (bundle.events.links ?? []).filter { $0.removed != true }, by: \.bounceId)
        func identity(_ scene: Int, _ track: Int?, _ time: Double) -> String? { resolver.resolve(scene: scene, track: track, time: time) }
        func reason(_ e: AnalysisEvent, personal: Bool = true) -> String? {
            if e.excluded { return "excluded" }
            if !(start...end).contains(e.start) { return "outside_range" }
            if verified && !e.reviewed { return "unreviewed" }
            if personal, let participantId {
                let pid = identity(e.scene, e.playerId, e.start)
                if pid != participantId || (e.participantId != nil && e.participantId != pid) { return "unresolved_or_other_identity" }
            }
            return nil
        }
        func metric(_ id: String, _ included: [AnalysisEvent], _ excluded: [String: String], refs: [String]? = nil, points: [ReviewPoint]? = nil, value: Double? = nil) -> ReviewMetric {
            let ids = Array(Set(included.map(\.id))).sorted(), count = points?.count ?? included.count
            return ReviewMetric(id: id, value: count == 0 ? nil : (value ?? Double(count)), sampleCount: count,
                                eventIds: ids, supportRefs: Array(Set(refs ?? ids)).sorted(), exclusions: excluded, points: points ?? [])
        }
        let hits = bundle.events.events.filter { $0.kind == .hit }, accepted = hits.filter { reason($0) == nil }
        let excluded = Dictionary(uniqueKeysWithValues: hits.compactMap { e in reason(e).map { (e.id, $0) } })
        metrics = [metric("hits", accepted, excluded)]
        for stroke in Stroke.allCases {
            let selected = accepted.filter { $0.stroke == stroke }
            var row = metric("stroke." + stroke.rawValue, selected, excluded)
            row.value = accepted.isEmpty ? nil : Double(selected.count); metrics.append(row)
        }
        var landings: [AnalysisEvent] = [], points: [ReviewPoint] = [], unassigned: [ReviewPoint] = [], skipped: [String: String] = [:], refs: [String] = []
        for bounce in bundle.events.events where bounce.kind == .bounce {
            try Task.checkCancellation()
            if let why = reason(bounce, personal: false) { skipped[bounce.id] = why; continue }
            guard let position = bounce.position else { skipped[bounce.id] = "missing_bounce_position"; continue }
            let links = linksByBounce[bounce.id] ?? []
            var pid: String?, hit: AnalysisEvent?
            if links.count == 1, !verified || links[0].reviewed,
               let shot = events[links[0].shotId], shot.kind == .hit, reason(shot, personal: false) == nil,
               shot.scene == bounce.scene, shot.start <= bounce.start {
                hit = shot; pid = identity(shot.scene, shot.playerId, shot.start)
                if shot.participantId != nil && shot.participantId != pid { pid = nil }
            }
            let point = ReviewPoint(reference: bounce.id, timestamp: bounce.start, position: position, participantId: pid)
            if pid == nil { unassigned.append(point) }
            if let participantId, pid != participantId { skipped[bounce.id] = "unresolved_or_other_identity"; continue }
            points.append(point); landings.append(bounce)
            if pid != nil, let hit { landings.append(hit); refs.append("link:" + links[0].id) }
        }
        metrics.append(metric("landings", landings, skipped, refs: refs + points.map(\.reference), points: points))
        metrics.append(metric("unassigned_landings", unassigned.compactMap { events[$0.reference] }, [:], points: unassigned))
        var rallyEvents: [AnalysisEvent] = [], rallyRefs: [String] = [], lengths: [Int] = [], rallyExcluded: [String: String] = [:]
        for rally in bundle.rallies.rallies {
            if rally.removed == true { rallyExcluded["rally:" + rally.id] = "removed"; continue }
            let shots = rally.shotIds.compactMap { events[$0] }
            guard !shots.isEmpty, shots.count == rally.shotIds.count, rally.reviewed,
                  shots.allSatisfy({ $0.kind == .hit && reason($0, personal: false) == nil }) else {
                rallyExcluded["rally:" + rally.id] = "missing_or_ineligible_shot_list"; continue
            }
            if participantId != nil && !shots.contains(where: { reason($0) == nil }) { rallyExcluded["rally:" + rally.id] = "unresolved_or_other_identity"; continue }
            lengths.append(shots.count); rallyEvents += shots; rallyRefs.append("rally:" + rally.id)
        }
        var rally = metric("rally_length", rallyEvents, rallyExcluded, refs: rallyRefs,
                           value: lengths.isEmpty ? nil : Double(lengths.reduce(0,+)) / Double(lengths.count))
        rally.sampleCount = lengths.count; metrics.append(rally)
        var positions: [ReviewPoint] = [], trackExcluded: [String: String] = [:]
        for (index, sample) in bundle.tracks.enumerated() {
            try Task.checkCancellation()
            let ref = "track:\(index)", pid = identity(sample.scene, sample.trackId, sample.timestamp)
            let why: String?
            if !(start...end).contains(sample.timestamp) { why = "outside_range" }
            else if verified && !sample.reviewed { why = "unreviewed" }
            else if sample.positionCourtM == nil { why = "missing_position" }
            else if participantId != nil && pid != participantId { why = "unresolved_or_other_identity" }
            else { why = nil }
            if let why { trackExcluded[ref] = why }
            else if let position = sample.positionCourtM { positions.append(ReviewPoint(reference: ref, timestamp: sample.timestamp, position: position, participantId: pid)) }
        }
        metrics.append(metric("player_positions", [], trackExcluded, refs: positions.map(\.reference), points: positions))
    }

    public static func identity(bundle: EvidenceBundle, scene: Int, track: Int?, time: Double) -> String? {
        ParticipantResolver(bundle).resolve(scene: scene, track: track, time: time)
    }
    private static func canonical(_ value: Any) -> Any {
        if let map = value as? [String: Any] { return map.filter { !($0.value is NSNull) }.mapValues(canonical) }
        if let array = value as? [Any] { return array.map(canonical) }
        if let number = value as? NSNumber, CFGetTypeID(number) != CFBooleanGetTypeID() {
            return String(format: "%.9f", locale: Locale(identifier: "en_US_POSIX"), number.doubleValue)
        }
        return value
    }
}

public struct ReviewQueueItem: Identifiable, Sendable {
    public var event: AnalysisEvent; public var priority: Int; public var reason: String
    public var id: String { event.id }
    public static func queue(_ bundle: EvidenceBundle) -> [Self] {
        bundle.events.events.compactMap { e -> Self? in
            guard !e.excluded else { return nil }
            if e.kind == .hit && ReviewReport.identity(bundle: bundle, scene: e.scene, track: e.playerId, time: e.start) == nil {
                return Self(event: e, priority: 0, reason: "identity")
            }
            if e.kind == .bounce && !(bundle.events.links ?? []).contains(where: { $0.bounceId == e.id && $0.reviewed && $0.removed != true }) {
                return Self(event: e, priority: 1, reason: "association")
            }
            return e.reviewed ? nil : Self(event: e, priority: 2, reason: "unreviewed")
        }.sorted { ($0.priority, $0.event.start, $0.id) < ($1.priority, $1.event.start, $1.id) }
    }
}
