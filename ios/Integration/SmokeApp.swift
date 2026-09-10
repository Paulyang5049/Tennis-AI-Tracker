import SwiftUI
import AVFoundation
import TennisCore
@main struct SmokeApp: App {
 var body: some Scene { WindowGroup { Text("Native integration check").task { await run() } } }
 func run() async {
  let docs=FileManager.default.urls(for:.documentDirectory,in:.userDomainMask)[0]
  var report:[String:Any]=[:]
  do {
   let item=try await LibraryImporter().importFile(docs.appendingPathComponent("input.mp4"),package:false,players:2)
   report["importedDuration"]=item.manifest.media.duration
   report["hasAudio"]=item.manifest.media.hasAudio
   report["origin"]=item.manifest.media.origin
   try await AnalysisEngine().run(item:item) { _ in }
   let manifest=try PackageIO.load(item.folder)
   let store=try AnalysisStore(url:item.folder.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
   report["frames"]=try store.state().nextFrame
   report["status"]=try store.status().rawValue
   guard let frame=try store.frame(at:0) else { throw PackageError.invalid("No review frame") }
   report["firstTimestamp"]=frame.timestamp
   var event=AnalysisEvent(kind:.hit,start:0.1); event.reviewed=true; event.favorite=true
   try store.saveEvent(event,duration:manifest.media.duration)
   report["verifiedHits"]=VerifiedStatistics(events:try store.events()).hits
   let clip=try await ClipExporter.export(item:item,event:event)
   let asset=AVURLAsset(url:clip)
   report["clipAudioTracks"]=try await asset.loadTracks(withMediaType:.audio).count
   report["clipDuration"]=try await asset.load(.duration).seconds
   try store.export(to:item.folder,manifest:manifest)
   let imported=try await LibraryImporter().importFile(item.folder,package:true,players:2)
   let reopened=try AnalysisStore(url:imported.folder.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:imported.manifest))
   report["roundtripHits"]=VerifiedStatistics(events:try reopened.events()).hits
   var oversized=manifest; oversized.media.duration=1e100
   try ContractJSON.write(oversized,to:item.folder.appendingPathComponent("manifest.json"))
   do { _=try LocalLibrary.importPackage(item.folder); report["rejectedOversized"]=false }
   catch { report["rejectedOversized"]=true }
   var partial=manifest; partial.status = .paused
   try ContractJSON.write(partial,to:item.folder.appendingPathComponent("manifest.json"))
   do { _=try LocalLibrary.importPackage(item.folder); report["rejectedPartial"]=false }
   catch { report["rejectedPartial"]=true }
   try ContractJSON.write(manifest,to:item.folder.appendingPathComponent("manifest.json"))
   let eventsURL=item.folder.appendingPathComponent(manifest.artifacts["events"]!)
   let savedEvents=try Data(contentsOf:eventsURL); try FileManager.default.removeItem(at:eventsURL)
   do { _=try LocalLibrary.importPackage(item.folder); report["rejectedMissingArtifact"]=false }
   catch { report["rejectedMissingArtifact"]=true }
   try savedEvents.write(to:eventsURL)
   report["success"]=true
  } catch { report["error"]=String(describing:error); report["success"]=false }
  if let data=try? JSONSerialization.data(withJSONObject:report,options:[.prettyPrinted,.sortedKeys]) { try? data.write(to:docs.appendingPathComponent("smoke-result.json")) }
 }
}
