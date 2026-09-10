import Foundation

// CLT-only fallback. XCTest suite remains authoritative when Xcode is available.
let fixture=URL(fileURLWithPath:CommandLine.arguments[1])
let root=FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString)
try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
defer { try? FileManager.default.removeItem(at:root) }
func check(_ value:Bool,_ message:String)throws { if !value { throw PackageError.invalid(message) } }
func rejects(_ action:()throws->Void)throws { do { try action() } catch { return }; throw PackageError.invalid("Expected rejection") }
let manifest=try PackageIO.load(fixture)
try check(manifest.schemaVersion==2 && manifest.settings.players==4,"fixture manifest")
var frames=[FrameRecord](); try PackageIO.readFrames(fixture.appendingPathComponent("frames.jsonl")) { frames.append($0) }
try check(frames.count==2 && frames[1].timestamp==0.0417,"fixture frames")
let collection=try ContractJSON.read(EventCollection.self,from:fixture.appendingPathComponent("events.json"))
try check(VerifiedStatistics(events:collection.events).hits==1,"verified statistics")
let store=try AnalysisStore(url:root.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
try store.importFrames(from:fixture.appendingPathComponent("frames.jsonl"))
let state=try store.state()
var bad=state; bad.nextFrame += 2; bad.lastTimestamp=1
try rejects { try store.checkpoint(frames:[FrameRecord(frame:state.nextFrame+1,timestamp:1)],events:[],state:bad) }
try check(try store.state()==state,"transaction rollback")
var other=manifest; other.modelProvenance=["changed":"yes"]
try rejects { _=try AnalysisStore(url:root.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:other)) }
try rejects { _=try PackageIO.asset("../escape",in:root) }
let h=try Homography.solve(points:[[0,0],[100,0],[0,100],[100,100]])
let point=Homography.project([100,100],matrix:h)!
try check(abs(point[0]-10.97)<1e-8 && abs(point[1]-23.77)<1e-8,"homography")
var continuous=RuntimeState(),resumed=RuntimeState()
for i in 0..<80 {
    func advance(_ s:inout RuntimeState) {
        let time=Double(i)/30
        let ball=s.ball.update(candidates:[Detection(box:[Double(i),10,Double(i)+4,14],confidence:0.9)],time:time,width:1920,height:1080)
        _=s.temporal.consume(FrameRecord(frame:i,timestamp:time,ball:ball)); s.nextFrame=i+1; s.lastTimestamp=time
    }
    advance(&continuous); advance(&resumed)
    if i==39 { resumed=try ContractJSON.decoder().decode(RuntimeState.self,from:ContractJSON.encoder().encode(resumed)) }
}
try check(continuous==resumed,"resumed tracking")
try store.export(to:root,manifest:manifest)
var roundtrip=[FrameRecord](); try PackageIO.readFrames(root.appendingPathComponent("frames.jsonl")) { roundtrip.append($0) }
try check(roundtrip==frames,"export roundtrip")
print("CoreCheck: fixtures, statistics, rollback, identity, path containment, homography, resume and export passed")
