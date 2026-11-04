import SwiftUI
import TennisCore

struct MatchSettingsEditor: View {
    let graph: EvidenceBundle; let duration: Double; let current: Double
    let save: ([CorrectedEntity]) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var selfName = ""
    @State private var opponentName = ""
    @State private var assignmentID = ""
    @State private var participant = "self"
    @State private var scene = 0
    @State private var track = 1
    @State private var side = "near"
    @State private var start = 0.0
    @State private var end = 0.0
    @State private var error: String?
    @State private var saving = false
    var body: some View {
        NavigationStack {
            Form {
                Section("Singles participants") {
                    TextField("Your name", text: $selfName)
                    TextField("Opponent name", text: $opponentName)
                    Text("Near and far are court sides, not player identities. Add a separate interval after each side change or scene cut.").font(.footnote)
                }
                Section("Identity interval") {
                    Picker("Edit interval", selection: $assignmentID) {
                        Text("New interval").tag("")
                        ForEach(graph.events.assignments ?? []) { Text("Scene \($0.scene) · P\($0.trackId) · \($0.start, specifier: "%.1f")–\($0.end, specifier: "%.1f")").tag($0.id) }
                    }.onChange(of: assignmentID) { _, id in
                        if let row = graph.events.assignments?.first(where: { $0.id == id }) {
                            scene = row.scene; track = row.trackId; side = row.side; start = row.start; end = row.end
                            participant = graph.events.participants?.first { $0.id == row.participantId }?.role ?? ""
                        }
                    }
                    Stepper("Scene \(scene)", value: $scene, in: 0...100000)
                    TextField("Track ID", value: $track, format: .number).keyboardType(.numbersAndPunctuation)
                    Picker("Court side", selection: $side) { Text("Near").tag("near"); Text("Far").tag("far") }
                    Picker("Participant", selection: $participant) { Text("Self").tag("self"); Text("Opponent").tag("opponent"); Text("Unresolved").tag("") }
                    TextField("Start seconds", value: $start, format: .number).keyboardType(.decimalPad)
                    TextField("End seconds", value: $end, format: .number).keyboardType(.decimalPad)
                }
                Section("Fields being confirmed") {
                    Text("Participant names, scene, track ID, court side and the selected time interval. Event actions and bounce coordinates are not confirmed here.")
                    Text("Overlapping intervals are rejected. Edit the earlier interval end before adding a side change.").font(.footnote)
                    if !assignmentID.isEmpty {
                        Text("Editing an interval retracts its previous event attribution. Statistics use the new mapping; other reviewed event fields stay unchanged.").font(.footnote)
                    }
                }
                if let error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("Match settings")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("Confirm fields") { commit() }.disabled(saving) }
                }
                .onAppear {
                    selfName = graph.events.participants?.first { $0.role == "self" }?.name ?? NSLocalizedString("Self", comment: "")
                    opponentName = graph.events.participants?.first { $0.role == "opponent" }?.name ?? NSLocalizedString("Opponent", comment: "")
                    start = min(current, duration); end = duration
                    if let event = graph.events.events.min(by: { abs($0.start-current) < abs($1.start-current) }) { scene = event.scene; track = event.playerId ?? 1 }
                }
        }
    }
    private func commit() {
        let selfID = graph.events.participants?.first { $0.role == "self" }?.id ?? "self"
        let opponentID = graph.events.participants?.first { $0.role == "opponent" }?.id ?? "opponent"
        let pid = participant == "self" ? selfID : participant == "opponent" ? opponentID : nil
        var entities: [CorrectedEntity] = [
            .participant(Participant(id: selfID, name: selfName, role: "self")),
            .participant(Participant(id: opponentID, name: opponentName, role: "opponent")),
            .assignment(SceneRoleAssignment(id: assignmentID.isEmpty ? UUID().uuidString : assignmentID, scene: scene, start: start, end: end,
                                            trackId: track, side: side, participantId: pid, reviewed: pid != nil, confidence: nil))
        ]
        if let previous = graph.events.assignments?.first(where: { $0.id == assignmentID }) {
            for var event in graph.events.events where event.participantId != nil && event.scene == previous.scene && event.playerId == previous.trackId && previous.start <= event.start && event.start < previous.end {
                // Retract stale attribution; the new interval supplies identity to statistics.
                event.participantId = nil
                entities.append(.event(event))
            }
        }
        saving = true
        Task { do { try await save(entities); dismiss() } catch { self.error = error.localizedDescription }; saving = false }
    }
}

struct AssociationEditor: View {
    let graph: EvidenceBundle
    let save: ([CorrectedEntity]) async throws -> Void
    @Environment(\.dismiss) private var dismiss
    @State private var mode = 0
    @State private var shot = ""
    @State private var bounce = ""
    @State private var linkID = ""
    @State private var rallyID = ""
    @State private var shots: [String] = []
    @State private var error: String?
    @State private var saving = false
    var body: some View {
        NavigationStack {
            Form {
                Picker("Association type", selection: $mode) { Text("Shot and bounce").tag(0); Text("Rally shots").tag(1) }
                if mode == 0 {
                    Picker("Existing association", selection: $linkID) {
                        Text("New association").tag("")
                        ForEach(graph.events.links ?? []) { link in
                            Text("\(link.shotId.prefix(8)) · \(link.bounceId.prefix(8))").tag(link.id)
                        }
                    }.accessibilityIdentifier("association.existing").onChange(of: linkID) { _, id in
                        if let link = graph.events.links?.first(where: { $0.id == id }) {
                            shot = link.shotId; bounce = link.bounceId
                        }
                    }
                    eventPicker("Shot", kind: .hit, selection: $shot)
                    eventPicker("Bounce", kind: .bounce, selection: $bounce)
                    Text("Both events must be reviewed first. This confirms only their association.").font(.footnote)
                    if let link = graph.events.links?.first(where: { $0.id == linkID }), link.reviewed {
                        Button("Retract association confirmation") { retract(link) }.disabled(saving)
                    }
                    if let link = graph.events.links?.first(where: { $0.id == linkID }), link.removed != true {
                        Button("Remove association") { remove(.link(link)) }.disabled(saving).accessibilityIdentifier("association.remove")
                    }
                } else {
                    Picker("Rally", selection: $rallyID) {
                        Text("New rally").tag("")
                        ForEach(graph.rallies.rallies) { Text("\($0.start, specifier: "%.2f")s · \($0.shotIds.count)").tag($0.id) }
                    }.onChange(of: rallyID) { _, id in shots = graph.rallies.rallies.first { $0.id == id }?.shotIds ?? [] }
                    ForEach(graph.events.events.filter { $0.kind == .hit && $0.reviewed && !$0.excluded }) { event in
                        Toggle("\(event.start, specifier: "%.2f")s · \(event.stroke.displayName)", isOn: Binding(get: { shots.contains(event.id) }, set: { selected in
                            shots.removeAll { $0 == event.id }; if selected { shots.append(event.id) }
                        }))
                    }
                    Text("Selected shots are saved in chronological order. Edit event times to correct the order. No match outcome is inferred.").font(.footnote)
                    if let rally = graph.rallies.rallies.first(where: { $0.id == rallyID }), rally.removed != true {
                        Button("Remove rally") { remove(.rally(rally)) }.disabled(saving)
                    }
                }
                Section("Fields being confirmed") {
                    Text(mode == 0 ? "Selected shot ID and bounce ID." : "Explicit chronological shot list and its time range.")
                    if mode == 1 { Text("Shots: \(shots.count)") }
                }
                if let error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("Review associations")
                .toolbar {
                    ToolbarItem(placement: .cancellationAction) { Button("Cancel") { dismiss() } }
                    ToolbarItem(placement: .confirmationAction) { Button("Confirm fields") { commit() }.disabled(saving) }
                }
        }
    }
    private func eventPicker(_ label: LocalizedStringKey, kind: EventKind, selection: Binding<String>) -> some View {
        Picker(label, selection: selection) {
            Text("Select an event").tag("")
            ForEach(graph.events.events.filter { $0.kind == kind && $0.reviewed && !$0.excluded }) { Text("\($0.start, specifier: "%.2f")s · \($0.id.prefix(8))").tag($0.id) }
        }.accessibilityIdentifier("association." + kind.rawValue)
    }
    private func commit() {
        do {
            let entity: CorrectedEntity
            if mode == 0 {
                guard !shot.isEmpty, !bounce.isEmpty else { throw PackageError.invalid(NSLocalizedString("Select both events", comment: "")) }
                let id = linkID.isEmpty ? (graph.events.links?.first { $0.bounceId == bounce }?.id ?? UUID().uuidString) : linkID
                entity = .link(ShotBounceLink(id: id, shotId: shot, bounceId: bounce, reviewed: true))
            } else {
                let ordered = graph.events.events.filter { shots.contains($0.id) }.sorted { ($0.start, $0.id) < ($1.start, $1.id) }
                guard let first = ordered.first, let last = ordered.last else { throw PackageError.invalid(NSLocalizedString("Select at least one shot", comment: "")) }
                entity = .rally(RallyEvidence(id: rallyID.isEmpty ? UUID().uuidString : rallyID, start: first.start, end: last.end, shotIds: ordered.map(\.id), reviewed: true))
            }
            saving = true
            Task { do { try await save([entity]); dismiss() } catch { self.error = error.localizedDescription }; saving = false }
        } catch { self.error = error.localizedDescription }
    }
    private func retract(_ link: ShotBounceLink) {
        var revised = link; revised.reviewed = false
        saving = true
        Task { do { try await save([.link(revised)]); dismiss() } catch { self.error = error.localizedDescription }; saving = false }
    }
    private func remove(_ entity: CorrectedEntity) {
        let revised: CorrectedEntity
        switch entity {
        case .link(var link): link.reviewed = false; link.removed = true; revised = .link(link)
        case .rally(var rally): rally.reviewed = false; rally.removed = true; revised = .rally(rally)
        default: return
        }
        saving = true
        Task { do { try await save([revised]); dismiss() } catch { self.error = error.localizedDescription }; saving = false }
    }
}
