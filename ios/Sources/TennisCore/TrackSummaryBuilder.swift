import Foundation

/// Portable automatic summary policy. Full-resolution observations remain in frames.
struct TrackSummaryBuilder {
    static let version = "candidate-first-per-half-second-v1"
    private(set) var samples: [PlayerPosition]
    private var buckets = Set<String>()
    private var bytes = 0
    init(existing: [PlayerPosition] = []) throws {
        samples = existing
        try EvidenceBundle.require(existing.count <= EvidenceBundle.maxRows, "Track collection exceeds row limit")
        for sample in existing {
            buckets.insert(try Self.bucket(sample))
            bytes += try ContractJSON.encoder().encode(sample).count + 1
        }
        try EvidenceBundle.require(bytes <= EvidenceBundle.maxBytes, "Track asset exceeds size limit")
    }
    static func bucket(_ sample: PlayerPosition) throws -> String {
        try EvidenceBundle.require(sample.timestamp >= 0 && (sample.timestamp * 2).isFinite, "Invalid track timestamp")
        return "\(sample.scene):\(sample.trackId):\(floor(sample.timestamp * 2))"
    }
    mutating func append(_ sample: PlayerPosition) throws {
        guard buckets.insert(try Self.bucket(sample)).inserted else { return }
        bytes += try ContractJSON.encoder().encode(sample).count + 1
        try EvidenceBundle.require(samples.count < EvidenceBundle.maxRows && bytes <= EvidenceBundle.maxBytes, "Track summary exceeds portable limits")
        samples.append(sample)
    }
}
