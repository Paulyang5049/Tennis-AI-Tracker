import SwiftUI
import TennisCore

/// One snapshot and filter set drives all three pages and their evidence links.
struct ReviewWorkspace: View {
    @Environment(\.dynamicTypeSize) private var dynamicTypeSize
    let item: MatchItem
    let store: AnalysisStore
    let events: [AnalysisEvent]
    let current: Double
    let refreshVersion: Int
    let seek: (Double) -> Void
    let edit: (AnalysisEvent) -> Void
    let changed: () -> Void
    @State private var page = 0
    @State private var evidenceView = EvidenceView.assisted
    @State private var participant = ""
    @State private var start = 0.0
    @State private var end = 0.0
    @State private var graph: EvidenceBundle?
    @State private var report: ReviewReport?
    @State private var limit = 40
    @State private var support: ReviewMetric?
    @State private var settings = false
    @State private var associations = false
    @State private var error: String?
    @State private var exportChoice: ReviewExportKind?
    @State private var shareURL: URL?
    @State private var loading = false
    @State private var revision = 0
    @State private var status: AnalysisStatus = .paused
    @State private var queue: [ReviewQueueItem] = []
    @State private var positionCount = 0

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading) {
                    Button("Assisted estimate") { evidenceView = .assisted }.accessibilityAddTraits(evidenceView == .assisted ? .isSelected : [])
                    Button("Human confirmed") { evidenceView = .humanVerified }.accessibilityAddTraits(evidenceView == .humanVerified ? .isSelected : [])
                }
            } else {
                Picker("Evidence view", selection: $evidenceView) {
                    Text("Assisted estimate").tag(EvidenceView.assisted)
                    Text("Human confirmed").tag(EvidenceView.humanVerified)
                }.pickerStyle(.segmented)
            }
            Text(evidenceView == .assisted ? "Estimates include unreviewed candidates. They are not accuracy measurements." : "Only eligible reviewed evidence is included.").font(.footnote).foregroundStyle(.secondary)
            Picker("Participant", selection: $participant) {
                Text("All / unassigned").tag("")
                ForEach(graph?.events.participants ?? []) { Text($0.name).tag($0.id) }
            }
            DisclosureGroup("Time range") {
                TextField("Start seconds", value: $start, format: .number).keyboardType(.decimalPad)
                TextField("End seconds", value: $end, format: .number).keyboardType(.decimalPad)
            }
            if dynamicTypeSize.isAccessibilitySize {
                VStack(alignment: .leading) {
                    Button("Overview") { page = 0 }.accessibilityAddTraits(page == 0 ? .isSelected : [])
                    Button("Review") { page = 1 }.accessibilityAddTraits(page == 1 ? .isSelected : [])
                    Button("Court") { page = 2 }.accessibilityAddTraits(page == 2 ? .isSelected : [])
                }
            } else {
                Picker("Match pages", selection: $page) {
                    Text("Overview").tag(0); Text("Review").tag(1); Text("Court").tag(2)
                }.pickerStyle(.segmented)
            }
            if loading { ProgressView("Updating evidence…") }
            if let graph, let report {
                if page == 0 { overview(graph, report) }
                else if page == 1 { review(graph) }
                else { court(report) }
            } else if !loading { Text("No analysis evidence yet. Start analysis or import a completed package.") }
            if item.manifest.schemaVersion == 3 {
                Button("Match settings and side changes") { settings = true }.accessibilityIdentifier("matchSettings")
                Button("Shot, bounce and rally associations") { associations = true }.disabled(graph == nil)
            } else { Text("Save a new v3 copy to edit identities and associations.").font(.footnote) }
            Menu("Export…") {
                Button("Statistics report · no media") { exportChoice = .report }.accessibilityIdentifier("exportReport")
                Button("Clip around current time") { exportChoice = .clip }.accessibilityIdentifier("exportClip")
                Button("Full analysis package") { exportChoice = .package }.accessibilityIdentifier("exportPackage")
            }.disabled(report == nil || loading).accessibilityIdentifier("exportMenu")
            if let shareURL { ShareLink("Share prepared export", item: shareURL).accessibilityIdentifier("shareExport") }
        }
        .task { end = item.manifest.media.duration }
        .task(id: revision) { if end > 0 { await reload() } }
        .onChange(of: events) { _, _ in invalidate() }
        .onChange(of: refreshVersion) { _, _ in invalidate() }
        .onChange(of: evidenceView) { _, _ in invalidate() }
        .onChange(of: participant) { _, _ in invalidate() }
        .onChange(of: start) { _, _ in invalidate() }
        .onChange(of: end) { _, _ in invalidate() }
        .sheet(item: $support) { metric in evidenceList(metric) }
        .sheet(isPresented: $settings) {
            if let graph { MatchSettingsEditor(graph: graph, duration: item.manifest.media.duration, current: current) { entities in
                try await save(entities, reason: "match identity and side-change review")
            } }
        }
        .sheet(isPresented: $associations) {
            if let graph { AssociationEditor(graph: graph) { entities in
                try await save(entities, reason: "shot bounce and rally association review")
            } }
        }
        .confirmationDialog("Export contents", isPresented: Binding(get: { exportChoice != nil }, set: { if !$0 { exportChoice = nil } }), titleVisibility: .visible) {
            if let choice = exportChoice { Button("Prepare export") { exportChoice = nil; prepare(choice) } }
            Button("Cancel", role: .cancel) { exportChoice = nil }
        } message: { Text(exportChoice?.contents ?? "") }
        .alert("Notice", isPresented: Binding(get: { error != nil }, set: { if !$0 { error = nil } })) {
            Button("OK") { error = nil }
        } message: { Text(error ?? "") }
    }
    @ViewBuilder private func overview(_ graph: EvidenceBundle, _ report: ReviewReport) -> some View {
        Text("Analysis status: \(status.rawValue)")
        Text("Pending review: \(queue.count)")
        Text("Available events: \(graph.events.events.count)")
        Text("Positions with calibration: \(positionCount) / \(graph.tracks.count)")
        Text("Quality reflects usable evidence coverage, not detection accuracy.").font(.footnote)
        if status != .complete { Text("Analysis is incomplete. These statistics cover available evidence only.").foregroundStyle(.orange) }
        ForEach(report.metrics.filter { !$0.id.hasPrefix("stroke.") || $0.value != 0 }) { metric in
            Button { support = metric } label: {
                let layout = dynamicTypeSize.isAccessibilitySize ? AnyLayout(VStackLayout(alignment: .leading)) : AnyLayout(HStackLayout())
                layout {
                    Text(metric.title)
                    if !dynamicTypeSize.isAccessibilitySize { Spacer() }
                    if let value = metric.value { Text(value, format: .number.precision(.fractionLength(0...2))) }
                    else { Text("Insufficient data") }
                }.fixedSize(horizontal: false, vertical: true).padding(.vertical, 6)
            }.accessibilityHint("Show supporting events").accessibilityIdentifier("metric." + metric.id)
        }
    }
    @ViewBuilder private func review(_ graph: EvidenceBundle) -> some View {
        if queue.isEmpty { Text("No events pending in this range.") }
        LazyVStack(alignment: .leading, spacing: 14) {
            ForEach(Array(queue.prefix(limit))) { row in
                VStack(alignment: .leading) {
                    Button { seek(max(0, row.event.start - 2)) } label: { Text("\(row.event.start, specifier: "%.2f")s · \(row.event.kind.displayName)") }
                    Text(NSLocalizedString("review." + row.reason, comment: "")).font(.caption)
                    HStack {
                        Button("Review fields") { edit(row.event) }
                        if row.priority == 0 { Button("Resolve identity") { settings = true } }
                        if row.priority == 1 { Button("Link shot") { associations = true } }
                    }
                }
            }
            if limit < queue.count { Button("Load more") { limit += 40 } }
        }
        DisclosureGroup("All events") {
            ForEach(Array(events.filter { (start...max(start,end)).contains($0.start) }.prefix(limit))) { event in
                HStack { Button("\(event.start, specifier: "%.2f")s · \(event.kind.displayName)") { seek(event.start) }; Spacer(); Button("Edit") { edit(event) }.accessibilityIdentifier("edit.event." + event.id) }
            }
            if limit < events.count { Button("Load more") { limit += 40 } }
        }
    }
    @ViewBuilder private func court(_ report: ReviewReport) -> some View {
        ForEach(report.metrics.filter { ["landings", "player_positions"].contains($0.id) }) { metric in
            Text(metric.title).font(.headline)
            Text("Samples: \(metric.sampleCount)").font(.caption)
            if metric.points.isEmpty { Text("Insufficient data") }
            else {
                CourtEvidencePlot(points: metric.points, positions: metric.id == "player_positions")
                Button("Show supporting evidence") { support = metric }
            }
        }
        Text("Circles: ball bounces. Squares: player ground positions. Unassigned evidence remains separate.").font(.footnote)
    }
    private func evidenceList(_ metric: ReviewMetric) -> some View {
        let ids = Set(metric.eventIds)
        let supporting = events.filter { ids.contains($0.id) }
        let positions = metric.points.filter { $0.reference.hasPrefix("track:") }
        let exclusions = metric.exclusions.keys.sorted()
        return NavigationStack {
            List {
                Section("Supporting events") {
                    ForEach(Array(supporting.prefix(limit))) { event in
                        Button("\(event.start, specifier: "%.2f")s · \(event.kind.displayName)") { support = nil; seek(event.start) }
                            .accessibilityIdentifier("evidence.event." + event.id)
                    }
                    ForEach(Array(positions.prefix(limit).enumerated()), id: \.offset) { _, point in
                        Button("Player position · \(point.timestamp, specifier: "%.2f")s") { support = nil; seek(point.timestamp) }
                    }
                    if max(supporting.count, positions.count) > limit { Button("Load more") { limit += 40 } }
                }
                Section("Exclusions") {
                    ForEach(exclusions.prefix(limit), id: \.self) { id in Text("\(id): \(metric.exclusions[id]!)").font(.caption) }
                    if exclusions.count > limit { Button("Load more") { limit += 40 } }
                }
            }.navigationTitle(metric.title)
                .toolbar { ToolbarItem(placement: .cancellationAction) { Button("Close") { support = nil } } }
        }
    }
    private func invalidate() { report = nil; shareURL = nil; support = nil; limit = 40; revision += 1 }
    @MainActor private func reload() async {
        let token = revision, view = evidenceView, pid = participant.isEmpty ? nil : participant, lower = start, upper = end
        loading = true; report = nil
        do {
            let worker = Task.detached { () -> (EvidenceBundle, ReviewReport, AnalysisStatus, [ReviewQueueItem], Int) in
                let graph = try store.evidenceSnapshot()
                let report = try ReviewReport(bundle: graph, view: view, participantId: pid, start: lower, end: upper)
                let queue = ReviewQueueItem.queue(graph).filter { row in
                    (lower...upper).contains(row.event.start) && (pid == nil || ReviewReport.identity(bundle: graph, scene: row.event.scene, track: row.event.playerId, time: row.event.start) == pid)
                }
                return (graph, report, try store.status(), queue, graph.tracks.filter { $0.positionCourtM != nil }.count)
            }
            let snapshot = try await withTaskCancellationHandler { try await worker.value } onCancel: { worker.cancel() }
            guard token == revision, !Task.isCancelled else { return }
            graph = snapshot.0; report = snapshot.1; status = snapshot.2; queue = snapshot.3; positionCount = snapshot.4
        } catch { if token == revision { self.error = error.localizedDescription } }
        if token == revision { loading = false }
    }
    private func save(_ entities: [CorrectedEntity], reason: String) async throws {
        try await Task.detached { try store.saveReviewedEntities(entities, duration: item.manifest.media.duration, reason: reason) }.value
        invalidate(); changed()
    }
    private func prepare(_ kind: ReviewExportKind) {
        guard let report else { return }; loading = true; shareURL = nil; let token = revision
        Task { do { let url = try await ReviewExporter.prepare(kind, item: item, store: store, report: report, current: current)
                if token == revision { shareURL = url } }
            catch { self.error = error.localizedDescription }; loading = false }
    }
}

extension ReviewMetric {
    var title: String { NSLocalizedString("metric." + id, comment: "") }
}

struct CourtEvidencePlot: View {
    let points: [ReviewPoint]; let positions: Bool
    var body: some View {
        Canvas { context, size in
            let rect = CGRect(x: 12, y: 12, width: size.width - 24, height: size.height - 24)
            context.stroke(Path(rect), with: .color(.secondary), lineWidth: 2)
            var net = Path(); net.move(to: CGPoint(x: rect.minX, y: rect.midY)); net.addLine(to: CGPoint(x: rect.maxX, y: rect.midY))
            context.stroke(net, with: .color(.secondary), lineWidth: 1)
            for point in points {
                let x = rect.minX + point.position[0] / 10.97 * rect.width, y = rect.minY + point.position[1] / 23.77 * rect.height
                let dot = CGRect(x: x - 3, y: y - 3, width: 6, height: 6)
                context.fill(positions ? Path(dot) : Path(ellipseIn: dot), with: .color(point.participantId == nil ? .gray : positions ? .purple : .blue))
            }
        }.frame(height: 280).accessibilityLabel(positions ? "Player ground positions" : "Ball bounce positions")
            .accessibilityValue("\(points.count) samples").accessibilityHint("Use Show supporting evidence for an accessible list")
    }
}
