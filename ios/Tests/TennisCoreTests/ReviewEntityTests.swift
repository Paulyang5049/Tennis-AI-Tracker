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
    func testSharedRemovedLinkAuditReplaysAndInvalidatesStatistics() throws {
        let root = try temporaryDirectory(), source = fixtures.appendingPathComponent("full")
        let manifest = try PackageIO.load(source)
        var graph = try EvidenceBundle.load(source)
        graph.audit = try EvidenceBundle.readLines(EvidenceCorrection.self, fixtures.appendingPathComponent("removed-associations-audit.jsonl"))
        try graph.write(to: root, manifest: manifest)
        var stale = graph.events; stale.links?[0].removed = nil
        try ContractJSON.write(stale, to: root.appendingPathComponent("events.json"))
        let recovered = try EvidenceBundle.load(root, manifest: manifest)
        XCTAssertEqual(recovered.events.links?.first?.removed, true)
        XCTAssertTrue(recovered.metrics.metrics.isEmpty)
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
    func testRetractingIdentityRemovesPersonalStatisticsAndSurvivesReopen() throws {
        let root = try temporaryDirectory(), store = try store(root)
        var graph = try store.evidenceSnapshot()
        var assignment = try XCTUnwrap(graph.events.assignments?.first)
        assignment.participantId = nil; assignment.reviewed = false
        var shot = try XCTUnwrap(graph.events.events.first)
        shot.participantId = nil
        try store.saveReviewedEntities([.assignment(assignment), .event(shot)], duration: 5, reason: "identity unresolved")
        graph = try store.evidenceSnapshot()
        XCTAssertTrue(graph.events.events[0].reviewed)
        XCTAssertNil(try ReviewReport(bundle: graph, participantId: "self", end: 5).metrics.first { $0.id == "hits" }?.value)
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let reopened = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        XCTAssertEqual(try reopened.evidenceSnapshot(), graph)
    }
    func testSharedParticipantOverlapIsRejected() throws {
        var graph = try EvidenceBundle.load(fixtures.appendingPathComponent("full"))
        graph.events.assignments = try ContractJSON.read([SceneRoleAssignment].self, from: fixtures.appendingPathComponent("overlapping-participant-assignments.json"))
        XCTAssertThrowsError(try graph.validate(duration: 5))
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
    func testCalibrationRecomputesFramesAndExpiresAfterMotion() throws {
        let root = try temporaryDirectory(), store = try store(root)
        let player = Player(id: 1, box: [30, 20, 50, 60], confidence: 0.9)
        var frames = (0..<4).map { FrameRecord(frame: $0, timestamp: Double($0), players: [player]) }
        frames[2].cameraMoving = true
        var state = RuntimeState(); state.nextFrame = 4; state.lastTimestamp = 3
        try store.checkpoint(frames: frames, events: [], state: state)
        var correction = Corrections()
        correction.court["0"] = [[0, 0], [100, 0], [0, 100], [100, 100]]
        try store.saveCorrections(correction)
        let before = try store.evidenceSnapshot()
        XCTAssertNotNil(before.tracks[0].positionCourtM)
        XCTAssertNotNil(before.tracks[1].positionCourtM)
        XCTAssertNil(before.tracks[2].positionCourtM)
        XCTAssertNil(before.tracks[3].positionCourtM)
        correction.court["0"] = [[0, 0], [200, 0], [0, 200], [200, 200]]
        try store.saveCorrections(correction)
        let changed = try store.evidenceSnapshot()
        XCTAssertNotEqual(before.tracks[0].positionCourtM, changed.tracks[0].positionCourtM)
        XCTAssertNotEqual(try ReviewReport(bundle: before, end: 5).inputDigest, try ReviewReport(bundle: changed, end: 5).inputDigest)
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let reopened = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        XCTAssertEqual(try reopened.evidenceSnapshot(), changed)
    }
    func testIncrementalTrackCheckpointResumeAndExport() throws {
        let root = try temporaryDirectory()
        var manifest = try PackageIO.load(fixtures.appendingPathComponent("full")); manifest.media.duration = 1800
        let url = root.appendingPathComponent("analysis.sqlite"), identity = ResumeIdentity(manifest: manifest)
        var store = try AnalysisStore(url: url, identity: identity)
        try store.importEvidence(EvidenceBundle.load(fixtures.appendingPathComponent("full")), duration: 1800)
        for batch in 0..<60 {
            if batch == 30 { store = try AnalysisStore(url: url, identity: identity) }
            let frames = (batch * 60 ..< (batch + 1) * 60).map { index in
                let time = Double(index) / 2
                let players = (1...2).map { id in
                    var player = Player(id: id, box: [0, 0, 10, 10], confidence: 0.8)
                    player.courtPosition = PlayerPosition(timestamp: time, scene: 0, trackId: id, side: "unknown")
                    return player
                }
                return FrameRecord(frame: index, timestamp: time, players: players)
            }
            var state = try store.state(); state.nextFrame = (batch + 1) * 60; state.lastTimestamp = try XCTUnwrap(frames.last).timestamp
            try store.checkpoint(frames: frames, events: [], state: state)
        }
        let graph = try store.evidenceSnapshot()
        XCTAssertEqual(graph.tracks.count, 7200)
        try graph.validate(duration: 1800)
        try store.export(to: root, manifest: manifest)
        XCTAssertEqual(try EvidenceBundle.load(root, manifest: manifest), graph)
        XCTAssertEqual(try PackageIO.load(root).derivationVersions?["automatic_track_sampling"], TrackSummaryBuilder.version)
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
    func testRetractedAssociationAllowsEventReReview() throws {
        let root = try temporaryDirectory(), store = try self.store(root)
        var graph = try store.evidenceSnapshot()
        var link = try XCTUnwrap(graph.events.links?.first); link.reviewed = false
        try store.saveReviewedEntity(.link(link), duration: 5, reason: "retract association confirmation")
        var event = graph.events.events[0]; event.reviewed = false
        try store.saveReviewedEntity(.event(event), duration: 5, reason: "review again")
        graph = try store.evidenceSnapshot()
        XCTAssertFalse(graph.events.events[0].reviewed)
        XCTAssertFalse(try XCTUnwrap(graph.events.links?.first).reviewed)
        XCTAssertEqual(graph.audit.map(\.entityType).suffix(2), ["link", "event"])
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let reopened = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        XCTAssertEqual(try reopened.evidenceSnapshot(), graph)
    }
    func testRemovedAssociationsAllowEventReclassificationAndRecovery() throws {
        let root = try temporaryDirectory(), store = try self.store(root)
        var graph = try store.evidenceSnapshot()
        var link = try XCTUnwrap(graph.events.links?.first)
        link.reviewed = false; link.removed = true
        try store.saveReviewedEntity(.link(link), duration: 5, reason: "remove wrong link")
        XCTAssertEqual(try store.evidenceSnapshot().events.links?.first?.removed, true)
        let rally = RallyEvidence(id: "wrong-rally", start: 1, end: 1, shotIds: ["shot-1"], reviewed: true)
        try store.saveReviewedEntity(.rally(rally), duration: 5, reason: "create rally")
        var removedRally = rally; removedRally.reviewed = false; removedRally.removed = true
        try store.saveReviewedEntity(.rally(removedRally), duration: 5, reason: "remove wrong rally")
        XCTAssertEqual(try store.evidenceSnapshot().events.links?.first?.removed, true)
        XCTAssertEqual(try store.evidenceSnapshot().rallies.rallies.first?.removed, true)
        var event = graph.events.events[0]; event.kind = .bounce
        event.contactPointImagePx = nil; event.hitterPositionCourtM = nil
        try store.saveEvent(event, duration: 5)
        graph = try store.evidenceSnapshot()
        XCTAssertEqual(graph.events.events[0].kind, .bounce)
        XCTAssertEqual(graph.events.links?.first?.removed, true)
        XCTAssertEqual(graph.rallies.rallies.first?.removed, true)
        XCTAssertNil(try ReviewReport(bundle: graph, view: .humanVerified, end: 5).metrics.first { $0.id == "hits" }?.value)
        let manifest = try PackageIO.load(fixtures.appendingPathComponent("full"))
        let reopened = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        XCTAssertEqual(try reopened.evidenceSnapshot(), graph)
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
