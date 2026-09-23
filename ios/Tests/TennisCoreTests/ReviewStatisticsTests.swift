import Foundation
import XCTest
@testable import TennisCore

final class ReviewStatisticsTests: XCTestCase {
    private var fixture: URL { URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("contracts/fixtures/v3/full") }
    func testTrackSamplingSharedFixtureAndLongMatch() throws {
        let root = fixture.deletingLastPathComponent()
        let policy = try ContractJSON.read([String: [Double]].self, from: root.appendingPathComponent("track-sampling-v1.json"))
        var sample = try XCTUnwrap(EvidenceBundle.readLines(PlayerPosition.self, root.appendingPathComponent("legacy-track.jsonl")).first)
        var summary = try TrackSummaryBuilder()
        for time in try XCTUnwrap(policy["timestamps"]) {
            sample.timestamp = time; try summary.append(sample)
        }
        XCTAssertEqual(summary.samples.map(\.timestamp), policy["retained"])
        summary = try TrackSummaryBuilder()
        for frame in 0..<54_000 {
            sample.timestamp = Double(frame) / 30
            for id in 1...2 { sample.trackId = id; try summary.append(sample) }
        }
        XCTAssertEqual(summary.samples.count, 7200)
        sample.reviewed = true
        var retained = try TrackSummaryBuilder(existing: [sample])
        sample.reviewed = false; try retained.append(sample)
        XCTAssertTrue(try XCTUnwrap(retained.samples.first).reviewed)
    }
    func testEvidenceViewsAndDigest() throws {
        var graph = try EvidenceBundle.load(fixture)
        let report = try ReviewReport(bundle: graph, view: .humanVerified, participantId: "self", end: 5)
        XCTAssertEqual(report.metrics.first { $0.id == "hits" }?.value, 1)
        XCTAssertEqual(report.metrics.first { $0.id == "stroke.unknown" }?.value, 1)
        XCTAssertEqual(report.metrics.first { $0.id == "landings" }?.eventIds, ["bounce-1", "shot-1"])
        graph.events.links?[0].reviewed = false
        let changed = try ReviewReport(bundle: graph, view: .humanVerified, participantId: "self", end: 5)
        XCTAssertNotEqual(report.inputDigest, changed.inputDigest)
        XCTAssertNil(changed.metrics.first { $0.id == "landings" }?.value)
        let assisted = try ReviewReport(bundle: graph, participantId: "self", end: 5)
        XCTAssertEqual(assisted.metrics.first { $0.id == "landings" }?.value, 1)
    }
    func testNonemptyPositionsAndReviewedRallyLengths() throws {
        var graph = try EvidenceBundle.load(fixture)
        graph.tracks = try EvidenceBundle.readLines(PlayerPosition.self, fixture.deletingLastPathComponent().appendingPathComponent("report-tracks.jsonl"))
        for view in EvidenceView.allCases {
            let report = try ReviewReport(bundle: graph, view: view, participantId: "self", end: 3)
            let positions = try XCTUnwrap(report.metrics.first { $0.id == "player_positions" })
            let count = view == .assisted ? 2 : 1
            XCTAssertEqual(positions.value, Double(count))
            XCTAssertEqual(positions.sampleCount, count)
            XCTAssertEqual(positions.supportRefs, (0..<count).map { "track:\($0)" })
            XCTAssertEqual(positions.points.first?.position, [4, 2])
            XCTAssertEqual(positions.exclusions["track:2"], "missing_position")
            XCTAssertEqual(positions.exclusions["track:3"], "outside_range")
            XCTAssertEqual(positions.exclusions["track:4"], "unresolved_or_other_identity")
            if view == .humanVerified { XCTAssertEqual(positions.exclusions["track:1"], "unreviewed") }
        }
        var second = graph.events.events[0]; second.id = "shot-2"; second.start = 3; second.end = 3
        var third = second; third.id = "shot-3"; third.start = 4; third.end = 4
        graph.events.events += [second, third]
        graph.rallies.rallies = [RallyEvidence(id: "one", start: 1, end: 1, shotIds: ["shot-1"], reviewed: true),
            RallyEvidence(id: "two", start: 3, end: 4, shotIds: ["shot-2", "shot-3"], reviewed: true)]
        var rally = try XCTUnwrap(ReviewReport(bundle: graph, view: .humanVerified, end: 5).metrics.first { $0.id == "rally_length" })
        XCTAssertEqual(rally.value, 1.5); XCTAssertEqual(rally.sampleCount, 2)
        XCTAssertEqual(rally.eventIds, ["shot-1", "shot-2", "shot-3"])
        graph.events.events[3].reviewed = false
        rally = try XCTUnwrap(ReviewReport(bundle: graph, view: .humanVerified, end: 5).metrics.first { $0.id == "rally_length" })
        XCTAssertEqual(rally.value, 1)
        XCTAssertEqual(rally.exclusions, ["rally:two": "missing_or_ineligible_shot_list"])
    }
    func testSceneIsolationAndReviewQueue() throws {
        var graph = try EvidenceBundle.load(fixture)
        graph.events.events[0].scene = 1
        let report = try ReviewReport(bundle: graph, participantId: "self", end: 5)
        XCTAssertNil(report.metrics.first { $0.id == "hits" }?.value)
        XCTAssertEqual(ReviewQueueItem.queue(graph).first?.reason, "identity")
        graph.events.events[0].reviewed = false
        let verified = try ReviewReport(bundle: graph, view: .humanVerified, end: 5)
        XCTAssertNil(verified.metrics.first { $0.id == "hits" }?.value)
    }
}
