import Foundation
import XCTest
@testable import TennisCore

final class ReviewEntityTests: XCTestCase {
    private var fixtures: URL {
        URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
            .deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("contracts/fixtures/v3")
    }
    private func temporaryDirectory() throws -> URL {
        let root = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        addTeardownBlock { try? FileManager.default.removeItem(at: root) }
        return root
    }
    private func store(_ root: URL) throws -> AnalysisStore {
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let store = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        try store.importEvidence(EvidenceBundle.load(fixtures.appendingPathComponent("full")), duration: 5)
        return store
    }
    func testSharedLinkAuditReplayIsStableAndInvalidatesStaleMetrics() throws {
        let root = try temporaryDirectory(), source = fixtures.appendingPathComponent("full")
        let manifest = try PackageIO.load(source)
        var graph = try EvidenceBundle.load(source)
        graph.audit = try EvidenceBundle.readLines(EvidenceCorrection.self, fixtures.appendingPathComponent("link-audit.jsonl"))
        XCTAssertEqual(graph.audit.first?.after.kind, "link")
        try graph.write(to: root, manifest: manifest)
        XCTAssertEqual(try EvidenceBundle.load(root, manifest: manifest), graph)
        var stale = graph.events; stale.links = []
        try ContractJSON.write(stale, to: root.appendingPathComponent("events.json"))
        let recovered = try EvidenceBundle.load(root, manifest: manifest)
        XCTAssertEqual(recovered.events.links, graph.events.links)
        XCTAssertTrue(recovered.metrics.metrics.isEmpty)
        try recovered.write(to: root, manifest: manifest)
        XCTAssertEqual(try EvidenceBundle.load(root, manifest: manifest), recovered)
    }
    func testAtomicIdentityReviewAndRollback() throws {
        let store = try store(temporaryDirectory())
        let before = try store.evidenceSnapshot()
        var assignment = try XCTUnwrap(before.events.assignments?.first)
        assignment.participantId = "opponent"
        var hit = try XCTUnwrap(before.events.events.first)
        hit.participantId = "opponent"
        XCTAssertThrowsError(try store.saveReviewedEntity(.assignment(assignment), duration: 5, reason: "swap"))
        XCTAssertEqual(try store.evidenceSnapshot(), before)
        try store.saveReviewedEntities([
            .participant(Participant(id: "opponent", name: "Opponent", role: "opponent")),
            .assignment(assignment), .event(hit)
        ], duration: 5, reason: "identify together")
        let saved = try store.evidenceSnapshot()
        XCTAssertEqual(saved.audit.map(\.sequence), [1, 2, 3])
        XCTAssertEqual(saved.events.events.first?.participantId, "opponent")
        XCTAssertTrue(saved.metrics.metrics.isEmpty)
        XCTAssertTrue(saved.insights.insights.isEmpty)
        var overlapping = assignment; overlapping.id = "other-track"; overlapping.trackId = 2
        XCTAssertThrowsError(try store.saveReviewedEntity(.assignment(overlapping), duration: 5, reason: "overlap"))
        XCTAssertEqual(try store.evidenceSnapshot(), saved)
        var otherScene = hit; otherScene.scene = 1
        XCTAssertThrowsError(try store.saveReviewedEntity(.event(otherScene), duration: 5, reason: "cut"))
        XCTAssertEqual(try store.events(), saved.events.events)
    }
    func testCheckpointPreservesReviewedFieldsAndUpdatesSnapshot() throws {
        let store = try store(temporaryDirectory())
        let original = try store.events()
        var changed = original[0]; changed.contactPointImagePx = [999, 999]; changed.participantId = nil
        var candidate = AnalysisEvent(id: "new", kind: .hit, start: 3)
        candidate.reviewed = false; candidate.provenance = "automatic"
        try store.checkpoint(frames: [], events: [changed, candidate], state: store.state())
        let graph = try store.evidenceSnapshot()
        XCTAssertEqual(graph.events.events.first, original.first)
        XCTAssertEqual(graph.events.events.last, candidate)
    }
    func testCalibrationInvalidatesDerivedAssets() throws {
        let store = try store(temporaryDirectory())
        var corrections = Corrections()
        corrections.court["0"] = [[0, 0], [100, 0], [0, 100], [100, 100]]
        try store.saveCorrections(corrections)
        let graph = try store.evidenceSnapshot()
        XCTAssertTrue(graph.metrics.metrics.isEmpty)
        XCTAssertTrue(graph.insights.insights.isEmpty)
        XCTAssertEqual(try store.corrections(), corrections)
    }
    func testLinkReviewPersistsAndRejectsInvalidReferences() throws {
        let root = try temporaryDirectory(), store = try self.store(root)
        let link = ShotBounceLink(id: "link-2", shotId: "shot-1", bounceId: "bounce-1", reviewed: true)
        try store.saveReviewedEntity(.link(link), duration: 5, reason: "associate bounce")
        let saved = try store.evidenceSnapshot()
        XCTAssertEqual(saved.audit.last?.entityType, "link")
        XCTAssertEqual(saved.audit.last?.after, .link(link))
        XCTAssertNil(saved.audit.last?.before)
        XCTAssertTrue(saved.metrics.metrics.isEmpty)
        var invalid = link; invalid.bounceId = "shot-1"
        XCTAssertThrowsError(try store.saveReviewedEntity(.link(invalid), duration: 5, reason: "bad type"))
        invalid.bounceId = "missing"
        XCTAssertThrowsError(try store.saveReviewedEntity(.link(invalid), duration: 5, reason: "missing bounce"))
        XCTAssertEqual(try store.evidenceSnapshot(), saved)
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let reopened = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        XCTAssertEqual(try reopened.evidenceSnapshot(), saved)
    }
    func testFrameImportDoesNotDuplicateMaterializedTrackOrInheritSceneIdentity() throws {
        let store = try store(temporaryDirectory())
        var graph = try store.evidenceSnapshot()
        let position = PlayerPosition(timestamp: 0, scene: 1, trackId: 1, side: "unknown")
        graph.tracks = [position]
        try store.importEvidence(graph, duration: 5)
        var player = Player(id: 1, box: [0, 0, 10, 10], confidence: 0.8); player.courtPosition = position
        var frame = FrameRecord(frame: 0, timestamp: 0, players: [player]); frame.scene = 1
        var state = RuntimeState(); state.nextFrame = 1; state.lastTimestamp = 0
        var hit = AnalysisEvent(id: "scene-1-hit", kind: .hit, start: 3)
        hit.scene = 1; hit.playerId = 1; hit.reviewed = false; hit.provenance = "automatic"
        try store.checkpoint(frames: [frame], events: [hit], state: state)
        let saved = try store.evidenceSnapshot()
        XCTAssertEqual(saved.tracks, [position])
        XCTAssertNil(saved.events.events.last?.participantId)
        XCTAssertNil(saved.events.events.last?.hitterPositionCourtM)
        XCTAssertEqual(saved.events.assignments, graph.events.assignments)
    }
    func testCourtPositionRoundTripAndTrackSnapshotPreserveNulls() throws {
        let root = try temporaryDirectory(), store = try self.store(root)
        let position = PlayerPosition(timestamp: 0, scene: 0, trackId: 7, side: "unknown")
        var player = Player(id: 7, box: [0, 0, 10, 10], confidence: 0.8)
        player.courtPosition = position
        let frame = FrameRecord(frame: 0, timestamp: 0, players: [player])
        var state = RuntimeState(); state.nextFrame = 1; state.lastTimestamp = 0
        try store.checkpoint(frames: [frame], events: [], state: state)
        XCTAssertEqual(try store.frame(at: 0)?.players.first?.courtPosition, position)
        XCTAssertTrue(try store.evidenceSnapshot().tracks.contains(position))
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        try store.export(to: root, manifest: manifest)
        var exported: [FrameRecord] = []
        try PackageIO.readFrames(root.appendingPathComponent("frames.jsonl")) { exported.append($0) }
        XCTAssertEqual(exported, [frame])
        let text = try String(contentsOf: root.appendingPathComponent("frames.jsonl"), encoding: .utf8)
        XCTAssertTrue(text.contains("\"court_position\""))
        XCTAssertTrue(text.contains("\"calibration_id\":null"))
        XCTAssertTrue(text.contains("\"position_court_m\":null"))
        // The app imports frames before evidence; an empty tracks asset must not erase frame observations.
        let secondRoot = try temporaryDirectory()
        let second = try AnalysisStore(url: secondRoot.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        try second.importFrames(from: root.appendingPathComponent("frames.jsonl"))
        try second.importEvidence(EvidenceBundle.load(fixtures.appendingPathComponent("full")), duration: 5)
        XCTAssertTrue(try second.evidenceSnapshot().tracks.contains(position))
    }
}
