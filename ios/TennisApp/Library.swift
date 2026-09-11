import Foundation
import AVFoundation
import CryptoKit
import ImageIO
import TennisCore

struct MatchItem:Identifiable,Hashable,Sendable {
    let id:String; let folder:URL; var title:String; var manifest:Manifest
    static func ==(a:Self,b:Self)->Bool { a.id==b.id && a.manifest==b.manifest && a.title==b.title }
    func hash(into hasher:inout Hasher) { hasher.combine(id) }
}
struct LibraryMetadata:Codable { var title:String; var created:Date }

/// File copy, hashing and JSONL import stay off SwiftUI's main actor.
actor LibraryImporter {
    func importFile(_ source:URL,package:Bool,players:Int)async throws->MatchItem {
        if package { return try LocalLibrary.importPackage(source) }
        return try await LocalLibrary.importVideo(source,players:players)
    }
}

enum LocalLibrary {
    static var root:URL {
        FileManager.default.urls(for:.applicationSupportDirectory,in:.userDomainMask)[0].appendingPathComponent("Matches",isDirectory:true)
    }
    static func list()throws->[MatchItem] {
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        try protect(root)
        return try FileManager.default.contentsOfDirectory(at:root,includingPropertiesForKeys:[.creationDateKey],options:.skipsHiddenFiles).compactMap { url in
            guard let manifest=try? PackageIO.load(url),manifest.media.duration<=7200 else { return nil }
            let metadata=try? ContractJSON.read(LibraryMetadata.self,from:url.appendingPathComponent("library.json"))
            return MatchItem(id:url.lastPathComponent,folder:url,title:metadata?.title ?? url.lastPathComponent,manifest:manifest)
        }.sorted { $0.id > $1.id }
    }
    static func hash(_ url:URL)throws->String {
        let handle=try FileHandle(forReadingFrom:url); defer { try? handle.close() }; var hash=SHA256()
        while let data=try handle.read(upToCount:1_048_576),!data.isEmpty { try Task.checkCancellation(); hash.update(data:data) }
        return hash.finalize().map { String(format:"%02x",$0) }.joined()
    }
    static func importVideo(_ source:URL,players:Int)async throws->MatchItem {
        let access=source.startAccessingSecurityScopedResource(); defer { if access { source.stopAccessingSecurityScopedResource() } }
        try FileManager.default.createDirectory(at:root,withIntermediateDirectories:true)
        let size=(try source.resourceValues(forKeys:[.fileSizeKey])).fileSize ?? 0
        try checkStorage(required:Int64(size)+524_288_000)
        let folder=root.appendingPathComponent("\(Int(Date().timeIntervalSince1970))-\(UUID().uuidString)",isDirectory:true)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        do {
            try protect(folder)
            let target=folder.appendingPathComponent("source.\(source.pathExtension.lowercased())")
            try FileManager.default.copyItem(at:source,to:target)
            let asset=AVURLAsset(url:target)
            guard let track=try await asset.loadTracks(withMediaType:.video).first else { throw PackageError.invalid(String(localized:"import.videoMissing")) }
            let range=try await track.load(.timeRange),segments=try await track.load(.segments)
            let start=segments.first(where:{ !$0.isEmpty })?.timeMapping.target.start ?? range.start
            let end=segments.last(where:{ !$0.isEmpty })?.timeMapping.target.end ?? range.end
            let videoRange=CMTimeRange(start:start,end:end),duration=videoRange.duration.seconds
            guard duration.isFinite,duration>0,duration<=7200 else { throw PackageError.invalid(String(localized:"import.duration")) }
            let size=try await track.load(.naturalSize),transform=try await track.load(.preferredTransform)
            let oriented=size.applying(transform),width=abs(oriented.width),height=abs(oriented.height)
            let scale=min(1,1920/width,1080/height)
            let reader=try AVAssetReader(asset:asset)
            reader.timeRange=videoRange
            // Exclude empty leading edits; AVFoundation otherwise emits a synthetic black frame.
            // Use the same decoded presentation timeline as analysis and playback.
            // Compressed H.264 samples can expose a reorder offset before decoding.
            let output=AVAssetReaderTrackOutput(track:track,outputSettings:[kCVPixelBufferPixelFormatTypeKey as String:kCVPixelFormatType_32BGRA]); reader.add(output)
            guard reader.startReading(),let sample=output.copyNextSampleBuffer() else { throw PackageError.invalid("Cannot read first presentation timestamp") }
            let origin=CMSampleBufferGetPresentationTimeStamp(sample).seconds; reader.cancelReading()
            let fps=try await track.load(.nominalFrameRate),hasAudio=try await !asset.loadTracks(withMediaType:.audio).isEmpty
            let digest=try hash(target)
            let manifest=Manifest(media:.init(id:digest,path:target.lastPathComponent,width:Int(width*scale),height:Int(height*scale),duration:duration,origin:origin,fps:Double(fps),hasAudio:hasAudio),settings:.init(players:players))
            try ContractJSON.write(manifest,to:folder.appendingPathComponent("manifest.json"))
            try ContractJSON.write(Corrections(),to:folder.appendingPathComponent("corrections.json"))
            try ContractJSON.write(EventCollection(),to:folder.appendingPathComponent("events.json"))
            FileManager.default.createFile(atPath:folder.appendingPathComponent("frames.jsonl").path,contents:nil)
            let title=source.deletingPathExtension().lastPathComponent
            try ContractJSON.write(LibraryMetadata(title:title,created:Date()),to:folder.appendingPathComponent("library.json"))
            try protect(folder)
            return MatchItem(id:folder.lastPathComponent,folder:folder,title:title,manifest:manifest)
        } catch { try? FileManager.default.removeItem(at:folder); throw error }
    }
    static func importPackage(_ source:URL)throws->MatchItem {
        let access=source.startAccessingSecurityScopedResource(); defer { if access { source.stopAccessingSecurityScopedResource() } }
        let manifest=try PackageIO.load(source),folder=root.appendingPathComponent("\(Int(Date().timeIntervalSince1970))-\(UUID().uuidString)",isDirectory:true)
        guard manifest.media.duration<=7200 else { throw PackageError.invalid(String(localized:"import.duration")) }
        guard manifest.status == .complete else { throw PackageError.invalid("仅支持导入已完成的分析包；请在来源设备完成分析后重新导出。") }
        let isV2=FileManager.default.fileExists(atPath:source.appendingPathComponent("manifest.json").path)
        let required=[manifest.media.path,manifest.artifacts["frames"]!] + (manifest.schemaVersion == 3 ? Array(manifest.artifacts.values) : (isV2 ? [manifest.artifacts["events"]!,manifest.artifacts["corrections"]!] : []))
        let evidence = manifest.schemaVersion == 3 ? try EvidenceBundle.load(source, manifest: manifest) : nil
        var importBytes: Int64 = 0
        for relative in required {
            let url=try PackageIO.asset(relative,in:source)
            guard (try? url.resourceValues(forKeys:[.isRegularFileKey]).isRegularFile)==true else { throw PackageError.invalid("分析包缺少必要文件：\(relative)") }
            importBytes += Int64((try url.resourceValues(forKeys: [.fileSizeKey])).fileSize ?? 0)
        }
        try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
        try checkStorage(required: importBytes + 524_288_000)
        try FileManager.default.createDirectory(at:folder,withIntermediateDirectories:true)
        do {
            try protect(folder)
            for relative in [manifest.media.path]+Array(manifest.artifacts.values) {
                let input=try PackageIO.asset(relative,in:source),target=try PackageIO.asset(relative,in:folder)
                try FileManager.default.createDirectory(at:target.deletingLastPathComponent(),withIntermediateDirectories:true)
                if FileManager.default.fileExists(atPath:input.path) { try FileManager.default.copyItem(at:input,to:target) }
                else if relative==manifest.media.path { throw PackageError.invalid("Source video is missing from package") }
            }
            guard try hash(PackageIO.asset(manifest.media.path,in:folder))==manifest.media.sha256 else { throw PackageError.invalid("Package video checksum does not match manifest") }
            try ContractJSON.write(manifest,to:folder.appendingPathComponent("manifest.json"))
            let title=source.deletingPathExtension().lastPathComponent
            try ContractJSON.write(LibraryMetadata(title:title,created:Date()),to:folder.appendingPathComponent("library.json"))
            let store=try AnalysisStore(url:folder.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:manifest))
            let frames=try PackageIO.asset(manifest.artifacts["frames"]!,in:folder)
            if FileManager.default.fileExists(atPath:frames.path) { try store.importFrames(from:frames) }
            let eventsURL=try PackageIO.asset(manifest.artifacts["events"]!,in:folder)
            if let evidence {
                try store.importEvidence(evidence, duration: manifest.media.duration)
            } else if FileManager.default.fileExists(atPath:eventsURL.path) {
                let data = try EvidenceBundle.boundedImportData(eventsURL)
                let events=try ContractJSON.decoder().decode(EventCollection.self,from:data)
                guard events.schemaVersion==2 else { throw PackageError.unsupportedVersion(events.schemaVersion) }
                guard events.events.count <= 100_000, Set(events.events.map(\.id)).count == events.events.count else { throw PackageError.invalid("事件数量超限或 ID 重复") }
                for event in events.events { try store.saveEvent(event,duration:manifest.media.duration) }
            }
            let corrections=try PackageIO.asset(manifest.artifacts["corrections"]!,in:folder)
            if FileManager.default.fileExists(atPath:corrections.path) { try store.saveCorrections(ContractJSON.read(Corrections.self,from:corrections)) }
            try store.setStatus(.complete)
            try protect(folder)
            return MatchItem(id:folder.lastPathComponent,folder:folder,title:title,manifest:manifest)
        } catch { try? FileManager.default.removeItem(at:folder); throw error }
    }
    static func checkStorage(required:Int64=262_144_000)throws {
        let values=try root.resourceValues(forKeys:[.volumeAvailableCapacityForImportantUsageKey])
        if let available=values.volumeAvailableCapacityForImportantUsage,available<required { throw PackageError.invalid(String(localized:"storage.low")) }
    }
    static func remove(_ item:MatchItem)throws {
        let parent = root.resolvingSymlinksInPath().standardizedFileURL
        let values = try item.folder.resourceValues(forKeys: [.isSymbolicLinkKey])
        guard values.isSymbolicLink != true,
              item.folder.resolvingSymlinksInPath().standardizedFileURL.deletingLastPathComponent() == parent,
              item.folder.lastPathComponent == item.id else { throw PackageError.invalid("只能删除资料库内的指定比赛") }
        try FileManager.default.removeItem(at:item.folder)
    }
    static func protect(_ folder: URL) throws {
        var protected = folder
        var values = URLResourceValues(); values.isExcludedFromBackup = true
        try protected.setResourceValues(values)
        let attributes: [FileAttributeKey: Any] = [.protectionKey: FileProtectionType.completeUntilFirstUserAuthentication]
        try FileManager.default.setAttributes(attributes, ofItemAtPath: folder.path)
        if let files = FileManager.default.enumerator(at: folder, includingPropertiesForKeys: [.isSymbolicLinkKey]) {
            for case let file as URL in files {
                guard (try file.resourceValues(forKeys: [.isSymbolicLinkKey])).isSymbolicLink != true else { throw PackageError.invalid("资料库不接受符号链接") }
                try FileManager.default.setAttributes(attributes, ofItemAtPath: file.path)
            }
        }
    }
    static func saveAsV3(_ item: MatchItem) throws -> MatchItem {
        let manifest = try item.manifest.migratedToV3()
        guard item.manifest.schemaVersion == 2, item.manifest.status == .complete else { throw PackageError.invalid("请先完成 v2 分析后另存为 v3") }
        let folder = root.appendingPathComponent("\(Int(Date().timeIntervalSince1970))-\(UUID().uuidString)", isDirectory: true)
        try checkStorage(required: diskUsage(item) + 524_288_000)
        try FileManager.default.createDirectory(at: folder, withIntermediateDirectories: true)
        do {
            try protect(folder)
            let source = try PackageIO.asset(item.manifest.media.path, in: item.folder)
            let target = try PackageIO.asset(manifest.media.path, in: folder)
            try FileManager.default.createDirectory(at: target.deletingLastPathComponent(), withIntermediateDirectories: true)
            try FileManager.default.copyItem(at: source, to: target)
            let store = try AnalysisStore(url: item.folder.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: item.manifest))
            try store.export(to: folder, manifest: manifest)
            let title = item.title + " · v3"
            try ContractJSON.write(LibraryMetadata(title: title, created: Date()), to: folder.appendingPathComponent("library.json"))
            let migrated = try AnalysisStore(url: folder.appendingPathComponent("analysis.sqlite"), identity: ResumeIdentity(manifest: manifest))
            try migrated.importFrames(from: PackageIO.asset(manifest.artifacts["frames"]!, in: folder))
            try migrated.importEvidence(EvidenceBundle.load(folder), duration: manifest.media.duration)
            try migrated.saveCorrections(store.corrections()); try migrated.setStatus(.complete)
            try protect(folder)
            return MatchItem(id: folder.lastPathComponent, folder: folder, title: title, manifest: manifest)
        } catch { try? FileManager.default.removeItem(at: folder); throw error }
    }
    static func diskUsage(_ item:MatchItem)->Int64 {
        guard let files=FileManager.default.enumerator(at:item.folder,includingPropertiesForKeys:[.fileSizeKey,.isRegularFileKey]) else { return 0 }
        return files.compactMap { $0 as? URL }.reduce(0) { result,url in let v=try? url.resourceValues(forKeys:[.fileSizeKey,.isRegularFileKey]); return result+(v?.isRegularFile==true ? Int64(v?.fileSize ?? 0) : 0) }
    }
}
