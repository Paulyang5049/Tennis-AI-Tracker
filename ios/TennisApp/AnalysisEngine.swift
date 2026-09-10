import Foundation
import AVFoundation
import CoreImage
import TennisCore

/// Serial reader, one decoded buffer and at most 60 compact records in memory.
actor AnalysisEngine {
    func run(item:MatchItem,progress:@escaping @Sendable (Double)->Void)async throws {
        let detector=try ModelDetector()
        var manifest=try PackageIO.load(item.folder)
        if manifest.modelProvenance.isEmpty {
            manifest.modelProvenance=detector.provenance
            try ContractJSON.write(manifest,to:item.folder.appendingPathComponent("manifest.json"))
        }
        guard manifest.modelProvenance==detector.provenance else { throw PackageError.incompatibleResume }
        let store=try AnalysisStore(url:item.folder.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
        if try store.status() == .complete { return }
        var state=try store.state(),batch=[FrameRecord](),events=[AnalysisEvent]()
        var corrections=try store.corrections()
        var pausedForThermal=false
        let asset=AVURLAsset(url:try PackageIO.asset(manifest.media.path,in:item.folder))
        guard let track=try await asset.loadTracks(withMediaType:.video).first else { throw PackageError.invalid("视频轨道不存在") }
        let transform=try await track.load(.preferredTransform)
        let reader=try AVAssetReader(asset:asset)
        reader.timeRange=CMTimeRange(start:CMTime(seconds:manifest.media.origin,preferredTimescale:60000),duration:CMTime(seconds:manifest.media.duration,preferredTimescale:60000))
        let output=AVAssetReaderTrackOutput(track:track,outputSettings:[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA])
        output.alwaysCopiesSampleData=false; reader.add(output)
        // Decode from origin for exact VFR identity. Skipped frames never enter inference.
        guard reader.startReading() else { throw reader.error ?? PackageError.invalid("视频解码失败") }
        defer { reader.cancelReading() }
        func commit(_ status:AnalysisStatus)throws {
            try store.checkpoint(frames:batch,events:events,state:state,status:status)
            batch.removeAll(keepingCapacity:true); events.removeAll(keepingCapacity:true)
            manifest.status=status
            try ContractJSON.write(manifest,to:item.folder.appendingPathComponent("manifest.json"))
        }
        do {
            while true {
                try Task.checkCancellation()
                if ProcessInfo.processInfo.thermalState == .serious || ProcessInfo.processInfo.thermalState == .critical {
                    pausedForThermal=true; try commit(.paused); throw PackageError.invalid("设备温度较高，进度已保存。降温后可继续。")
                }
                var reachedEnd=false
                try autoreleasepool {
                    guard let sample=output.copyNextSampleBuffer() else { reachedEnd=true; return }
                    let time=CMSampleBufferGetPresentationTimeStamp(sample).seconds-manifest.media.origin
                    guard time.isFinite,time>=0,time>state.lastTimestamp else { return }
                    guard let buffer=CMSampleBufferGetImageBuffer(sample) else { throw PackageError.invalid("无法读取画面") }
                    let image=CIImage(cvPixelBuffer:buffer).transformed(by:transform)
                    let found=try detector.predict(image:image,width:manifest.media.width,height:manifest.media.height)
                    var frame=FrameRecord(frame:state.nextFrame,timestamp:time)
                    frame.scene=state.scene
                    frame.players=state.players.update(detections:found.players,time:time,count:manifest.settings.players,width:manifest.media.width,height:manifest.media.height)
                    frame.rackets=found.rackets; frame.ballCandidates=found.balls
                    frame.ball=state.ball.update(candidates:found.balls,time:time,width:manifest.media.width,height:manifest.media.height)
                    // Native inference currently uses one continuous scene; imported multi-scene
                    // packages are complete and are never resumed through this engine.
                    frame.court=try corrections.latestCourt(at:frame.frame)
                    events += state.temporal.consume(frame); batch.append(frame)
                    state.nextFrame += 1; state.lastTimestamp=time
                }
                if reachedEnd { break }
                if batch.count>=60 { try LocalLibrary.checkStorage(); try commit(.running); corrections=try store.corrections(); progress(state.lastTimestamp/manifest.media.duration) }
            }
            if reader.status == .failed { throw reader.error ?? PackageError.invalid("视频解码失败") }
            if let rally=state.temporal.finish(scene:state.scene) { events.append(rally) }
            try commit(.complete); try store.export(to:item.folder,manifest:manifest); progress(1)
        } catch {
            try? commit(error is CancellationError || pausedForThermal ? .paused : .failed)
            throw error
        }
    }
}

enum ClipExporter {
    static func export(item:MatchItem,event:AnalysisEvent)async throws->URL {
        try LocalLibrary.checkStorage()
        let asset=AVURLAsset(url:try PackageIO.asset(item.manifest.media.path,in:item.folder))
        guard let session=AVAssetExportSession(asset:asset,presetName:AVAssetExportPresetHighestQuality) else { throw PackageError.invalid("无法导出此视频格式") }
        let start=max(0,event.start-2),end=min(item.manifest.media.duration,event.end+2)
        session.timeRange=CMTimeRange(start:CMTime(seconds:start+item.manifest.media.origin,preferredTimescale:60000),duration:CMTime(seconds:end-start,preferredTimescale:60000))
        let folder=item.folder.appendingPathComponent("Clips",isDirectory:true)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        let url=folder.appendingPathComponent(UUID().uuidString+".mp4")
        do { try await session.export(to:url,as:.mp4); return url }
        catch { try? FileManager.default.removeItem(at:url); throw error }
    }
}
