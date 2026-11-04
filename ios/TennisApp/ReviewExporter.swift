import Foundation
import TennisCore

enum ReviewExportKind { case report, clip, package
    var contents: String {
        switch self {
        case .report: return NSLocalizedString("Includes statistics, evidence IDs and exclusion reasons. No video, audio or images.", comment: "")
        case .clip: return NSLocalizedString("Includes video and original audio around the current playback time.", comment: "")
        case .package: return NSLocalizedString("Includes the complete source video and audio, analysis, identities and review history.", comment: "")
        }
    }
}

actor ReviewExporter {
    static func prepare(_ kind: ReviewExportKind, item: MatchItem, store: AnalysisStore, report: ReviewReport, current: Double) async throws -> URL {
        if kind == .clip { return try await ClipExporter.export(item: item, event: AnalysisEvent(kind: .hit, start: min(current, item.manifest.media.duration))) }
        return try await Task.detached {
            try LocalLibrary.checkStorage(required: kind == .package ? LocalLibrary.diskUsage(item) + 262_144_000 : 16_777_216)
            let root = item.folder.appendingPathComponent("Exports", isDirectory: true).appendingPathComponent(UUID().uuidString, isDirectory: true)
            try FileManager.default.createDirectory(at: root, withIntermediateDirectories: true)
            do {
                if kind == .report {
                    let url = root.appendingPathComponent("statistics.json")
                    try ContractJSON.write(report, to: url); try LocalLibrary.protect(root); return url
                }
                var manifest = try PackageIO.load(item.folder); manifest.status = try store.status()
                guard manifest.status == .complete else { throw PackageError.invalid(NSLocalizedString("Complete analysis before exporting a full package.", comment: "")) }
                let video = try PackageIO.asset(manifest.media.path, in: root)
                try FileManager.default.createDirectory(at: video.deletingLastPathComponent(), withIntermediateDirectories: true)
                try FileManager.default.copyItem(at: PackageIO.asset(manifest.media.path, in: item.folder), to: video)
                try store.export(to: root, manifest: manifest)
                try LocalLibrary.protect(root)
                return root
            } catch { try? FileManager.default.removeItem(at: root); throw error }
        }.value
    }
}
