import Foundation
import XCTest
@testable import TennisCore

final class CoreTests: XCTestCase {
    func testV3SharedFixturesAndInvalidReferences() throws {
        for name in ["minimal", "uncertain", "corrected", "full"] {
            let root = fixture.appendingPathComponent("v3/\(name)")
            let manifest = try PackageIO.load(root)
            XCTAssertEqual(manifest.schemaVersion, 3)
            let graph = try EvidenceBundle.load(root, manifest: manifest)
            try graph.validate(duration: 5)
            let data = try ContractJSON.encoder().encode(graph)
            let decoded = try ContractJSON.decoder().decode(EvidenceBundle.self, from: data)
            XCTAssertEqual(decoded, graph)
        }
        var graph = try EvidenceBundle.load(fixture.appendingPathComponent("v3/full"))
        graph.events.links![0].bounceId = "missing"
        XCTAssertThrowsError(try graph.validate(duration: 5))
    }
    func testV3StoreAuditAndExport() throws {
        let source = fixture.appendingPathComponent("v3/full"), root = try temp()
        let manifest = try PackageIO.load(source)
        let store = try AnalysisStore(url: root.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
        try store.importEvidence(EvidenceBundle.load(source), duration: 5)
        var event = try XCTUnwrap(store.events().first)
        event.stroke = .backhand
        try store.saveEvent(event, duration: 5)
        try store.export(to: root, manifest: manifest)
        let exported = try EvidenceBundle.load(root)
        XCTAssertEqual(exported.audit.count, 1)
        XCTAssertEqual(exported.audit[0].before?.stroke, .unknown)
        XCTAssertEqual(exported.events.events[0].stroke, .backhand)
        let text = try String(contentsOf: root.appendingPathComponent("events.json"), encoding: .utf8)
        XCTAssertTrue(text.contains("\"confidence\":null"))
        XCTAssertEqual(exported.events.links?.count, 1)
    }
    func testExplicitV2MigrationPreservesLegacyPosition() throws {
        let original = try PackageIO.load(fixture)
        let migrated = try original.migratedToV3()
        XCTAssertEqual(original.schemaVersion, 2)
        XCTAssertEqual(migrated.schemaVersion, 3)
        XCTAssertEqual(migrated.migration?.fromVersion, 2)
        let events = try ContractJSON.read(EventCollection.self, from: fixture.appendingPathComponent("events.json"))
        let graph = EvidenceBundle.migrating(events: events.events)
        try graph.validate(duration: migrated.media.duration)
        XCTAssertEqual(graph.events.events.first(where: { $0.kind == .bounce })?.position,
                       events.events.first(where: { $0.kind == .bounce })?.position)
        XCTAssertTrue(graph.events.assignments!.isEmpty)
    }
    var fixture:URL { URL(fileURLWithPath:#filePath).deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().deletingLastPathComponent().appendingPathComponent("contracts/fixtures") }
    func temp()throws->URL { let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString); try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true); addTeardownBlock { try? FileManager.default.removeItem(at:root) }; return root }
    func testSharedFixturesAndRoundTrip()throws {
        let manifest=try PackageIO.load(fixture); XCTAssertEqual(manifest.settings.players,4); XCTAssertEqual(manifest.media.origin,5)
        var frames=[FrameRecord](); try PackageIO.readFrames(fixture.appendingPathComponent("frames.jsonl")) { frames.append($0) }
        XCTAssertEqual(frames.count,2); XCTAssertEqual(frames[1].timestamp,0.0417); XCTAssertNil(frames[1].ball.xy)
        let events=try ContractJSON.read(EventCollection.self,from:fixture.appendingPathComponent("events.json"))
        XCTAssertEqual(events.events.first?.playerId,1)
        let encoded=try ContractJSON.encoder().encode(events)
        XCTAssertTrue(String(decoding:encoded,as:UTF8.self).contains("player_id"))
        let stats=VerifiedStatistics(events:events.events); XCTAssertEqual(stats.hits,1); XCTAssertEqual(stats.rallies,0); XCTAssertEqual(stats.landingEvents.count,1)
    }
    func testPoseAndRacketOwnershipSurviveStoreExport()throws {
        let root=try temp(),manifest=try PackageIO.load(fixture)
        let store=try AnalysisStore(url:root.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
        var player=Player(id:7,box:[1,2,3,4],confidence:0.9); player.pose=[[12,34,0.8],[56,78,0.7]]
        var racket=Detection(box:[5,6,7,8],confidence:0.8); racket.playerId=7
        var frame=FrameRecord(frame:0,timestamp:0,players:[player]); frame.rackets=[racket]
        var state=RuntimeState(); state.nextFrame=1; state.lastTimestamp=0
        try store.checkpoint(frames:[frame],events:[],state:state)
        try store.export(to:root,manifest:manifest)
        var exported=[FrameRecord](); try PackageIO.readFrames(root.appendingPathComponent("frames.jsonl")) { exported.append($0) }
        XCTAssertEqual(exported.first?.players.first?.pose,player.pose)
        XCTAssertEqual(exported.first?.rackets.first?.playerId,7)
        let text=try String(contentsOf:root.appendingPathComponent("frames.jsonl"),encoding:.utf8)
        XCTAssertTrue(text.contains("player_id")); XCTAssertTrue(text.contains("pose"))
    }
    func testPathContainmentAndSymlink()throws {
        let root=try temp(),outside=try temp()
        XCTAssertThrowsError(try PackageIO.asset("../secret",in:root)); XCTAssertThrowsError(try PackageIO.asset("/secret",in:root))
        try FileManager.default.createSymbolicLink(at:root.appendingPathComponent("escape"),withDestinationURL:outside)
        XCTAssertThrowsError(try PackageIO.asset("escape/file",in:root)); XCTAssertNoThrow(try PackageIO.asset("sub/file",in:root))
    }
    func testLegacyReaderPreservesSource()throws {
        let root=try temp(); let summary:[String:Any] = ["schema_version":1,"source":root.appendingPathComponent("source.mp4").path,"source_sha256":"abc","video":["width":1920,"height":1080,"duration":12.0,"fps":30],"settings":["players":2],"status":"complete"]
        let data=try JSONSerialization.data(withJSONObject:summary); try data.write(to:root.appendingPathComponent("summary.json"))
        let value=try PackageIO.load(root); XCTAssertEqual(value.schemaVersion,2); XCTAssertEqual(value.media.path,"source.mp4")
        XCTAssertEqual(try Data(contentsOf:root.appendingPathComponent("summary.json")),data)
    }
    func testHomographyAndInvalidCorners()throws {
        let points=[[100.0,100.0],[500,100],[0,700],[600,700]],matrix=try Homography.solve(points:points)
        for (p,expected) in zip(points,[[0.0,0],[10.97,0],[0,23.77],[10.97,23.77]]) {
            let output=try XCTUnwrap(Homography.project(p,matrix:matrix)); XCTAssertEqual(output[0],expected[0],accuracy:1e-7); XCTAssertEqual(output[1],expected[1],accuracy:1e-7)
        }
        XCTAssertThrowsError(try Homography.solve(points:[[0,0],[1,1],[2,2],[3,3]]))
        XCTAssertThrowsError(try Homography.solve(points:[points[0],points[3],points[2],points[1]]))
    }
    func testCheckpointRollbackAndResumeIdentity()throws {
        let root=try temp(),manifest=try PackageIO.load(fixture),identity=ResumeIdentity(manifest:manifest),url=root.appendingPathComponent("analysis.sqlite")
        var store:AnalysisStore?=try AnalysisStore(url:url,identity:identity)
        var state=RuntimeState(); state.nextFrame=1; state.lastTimestamp=0
        state.players.tracks=[.init(id:9,box:[1,2,3,4],lastSeen:0,confidence:0.9)]; state.players.nextId=10
        try store!.checkpoint(frames:[.init(frame:0,timestamp:0)],events:[],state:state)
        var bad=state; bad.nextFrame=3; bad.lastTimestamp=0.2
        XCTAssertThrowsError(try store!.checkpoint(frames:[.init(frame:1,timestamp:0.1),.init(frame:3,timestamp:0.2)],events:[],state:bad))
        XCTAssertEqual(try store!.state(),state); XCTAssertNil(try store!.frame(at:0.1).map { $0.frame==1 ? $0 : nil } ?? nil)
        store=nil; store=try AnalysisStore(url:url,identity:identity); XCTAssertEqual(try store!.state(),state)
        var other=manifest; other.modelProvenance=["model":"changed"]
        XCTAssertThrowsError(try AnalysisStore(url:url,identity:ResumeIdentity(manifest:other)))
    }
    func testEventEditsAndExportDoNotChangeFrames()throws {
        let root=try temp(),manifest=try PackageIO.load(fixture),store=try AnalysisStore(url:root.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
        try store.importFrames(from:fixture.appendingPathComponent("frames.jsonl")); let before=try store.state()
        var event=AnalysisEvent(id:"event",kind:.hit,start:0.1); event.stroke = .forehand
        try store.saveEvent(event,duration:2); event.excluded=true; try store.saveEvent(event,duration:2)
        XCTAssertEqual(VerifiedStatistics(events:try store.events()).hits,0); XCTAssertEqual(try store.state(),before)
        try store.export(to:root,manifest:manifest)
        var frames=[FrameRecord](); try PackageIO.readFrames(root.appendingPathComponent("frames.jsonl")) { frames.append($0) }
        XCTAssertEqual(frames.count,2); XCTAssertEqual(try store.frame(at:0.0417)?.frame,1)
        XCTAssertEqual(try store.neighboringTime(0,forward:true),0.0417)
    }
    func testContinuousAndResumedTrackingIdentical()throws {
        var continuous=RuntimeState(),resumed=RuntimeState()
        for i in 0..<80 {
            let time=Double(i)/30,ball=[Detection(box:[Double(i)+50,60,Double(i)+54,64],confidence:0.9)]
            func advance(_ state:inout RuntimeState) {
                let value=state.ball.update(candidates:ball,time:time,width:1920,height:1080)
                let people=state.players.update(detections:[.init(box:[100+Double(i),200,200+Double(i),450],confidence:0.9)],time:time,count:4,width:1920,height:1080)
                let frame=FrameRecord(frame:i,timestamp:time,players:people,ball:value)
                _=state.temporal.consume(frame); state.nextFrame=i+1; state.lastTimestamp=time
            }
            advance(&continuous); advance(&resumed)
            if i==39 { resumed=try ContractJSON.decoder().decode(RuntimeState.self,from:ContractJSON.encoder().encode(resumed)) }
        }
        XCTAssertEqual(continuous,resumed); XCTAssertEqual(resumed.players.tracks.first?.id,1)
    }
    func testFrameIndexedCourt()throws {
        var corrections=Corrections()
        corrections.court["30"]=[[100,100],[500,100],[0,700],[600,700]]
        XCTAssertNil(try corrections.latestCourt(at:29))
        XCTAssertNotNil(try corrections.latestCourt(at:30))
        XCTAssertEqual(try corrections.latestCourt(at:31),try corrections.latestCourt(at:30))
    }
    func testLandingPositionIsBounceOnly()throws {
        var event=AnalysisEvent(kind:.hit,start:1); event.position=[2,3]
        XCTAssertThrowsError(try event.validate(duration:5))
        event.kind = .rally; XCTAssertThrowsError(try event.validate(duration:5))
        event.kind = .bounce; XCTAssertNoThrow(try event.validate(duration:5))
    }
    func testUnreviewedManualEventIsNotVerified() {
        var event=AnalysisEvent(kind:.hit,start:1); event.reviewed=false
        XCTAssertEqual(VerifiedStatistics(events:[event]).hits,0)
        event.reviewed=true; XCTAssertEqual(VerifiedStatistics(events:[event]).hits,1)
        event.excluded=true; XCTAssertEqual(VerifiedStatistics(events:[event]).hits,0)
    }
    func testInvalidEventRejected()throws {
        var e=AnalysisEvent(kind:.hit,start:1,end:2); XCTAssertThrowsError(try e.validate(duration:5))
        e.kind = .rally; XCTAssertNoThrow(try e.validate(duration:5)); e.end=6; XCTAssertThrowsError(try e.validate(duration:5))
    }
}
