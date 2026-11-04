import SwiftUI
import TennisCore

struct EventEditor:View {
    @Environment(\.dismiss) private var dismiss
    @State var event:AnalysisEvent
    let duration:Double
    let save:(AnalysisEvent)async throws->Void
    @State private var x=""
    @State private var y=""
    @State private var playerID=""
    @State private var participantID=""
    @State private var error:String?
    @State private var saving = false
    var body:some View {
        NavigationStack {
            Form {
                Picker("类型",selection:$event.kind) { ForEach(EventKind.allCases,id:\.self) { Text($0.displayName).tag($0) } }.accessibilityIdentifier("event.kind")
                TextField("起始秒数",value:$event.start,format:.number).keyboardType(.decimalPad)
                if event.kind == .rally { TextField("结束秒数",value:$event.end,format:.number).keyboardType(.decimalPad) }
                TextField("球员 ID（可留空）",text:$playerID).keyboardType(.numberPad)
                TextField("Participant ID (optional)", text: $participantID)
                Stepper("Scene \(event.scene)", value: $event.scene, in: 0...100000)
                if event.kind == .hit { Picker("动作",selection:$event.stroke) { ForEach(Stroke.allCases,id:\.self) { Text($0.displayName).tag($0) } } }
                if event.kind == .bounce {
                    Text("落点以双打场地米数记录，左上角为原点；无法确认时留空。")
                    TextField("横向 0–10.97 米",text:$x).keyboardType(.decimalPad)
                    TextField("纵向 0–23.77 米",text:$y).keyboardType(.decimalPad)
                }
                Toggle("已复核",isOn:$event.reviewed); Toggle("排除此事件",isOn:$event.excluded); Toggle("收藏",isOn:$event.favorite)
                Section("Fields being confirmed") {
                    Text("Event type, time, track ID, action, entered bounce coordinates and exclusion state. Empty fields stay unknown.")
                    if event.kind == .hit {
                        if let point = event.contactPointImagePx { Text("Contact image pixels: \(point[0], specifier: "%.1f"), \(point[1], specifier: "%.1f")") }
                        if let point = event.hitterPositionCourtM { Text("Player court meters: \(point[0], specifier: "%.2f"), \(point[1], specifier: "%.2f")") }
                        if let range = event.contactInterval { Text("Contact interval: \(range[0], specifier: "%.3f")–\(range[1], specifier: "%.3f")s") }
                    }
                }
                if let error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("编辑事件")
            .toolbar {
                ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement:.confirmationAction) { Button("保存") {
                    do {
                        if event.kind != .rally { event.end=event.start }
                        if !playerID.isEmpty && Int(playerID)==nil { throw PackageError.invalid("球员 ID 应为整数") }
                        event.playerId=Int(playerID)
                        event.participantId=participantID.isEmpty ? nil : participantID
                        if event.kind != .hit { event.contactInterval=nil; event.contactPointImagePx=nil; event.hitterPositionCourtM=nil; event.stroke = .unknown }
                        if event.kind != .bounce { event.positionSource=nil }
                        if event.kind == .bounce && (!x.isEmpty || !y.isEmpty) {
                            guard let px=Double(x),let py=Double(y),px.isFinite,py.isFinite else { throw PackageError.invalid("请填写两个有效落点坐标") }
                            event.position=[px,py]
                        } else { event.position=nil }
                        try event.validate(duration:duration)
                        saving = true
                        Task { do { try await save(event); dismiss() }
                            catch { self.error = error.localizedDescription }; saving = false }
                    } catch { self.error=error.localizedDescription }
                }.disabled(saving).accessibilityIdentifier("saveEvent") }
            }.onAppear { playerID=event.playerId.map(String.init) ?? ""; participantID=event.participantId ?? ""; if let p=event.position { x=String(p[0]); y=String(p[1]) } }
        }
    }
}

extension EventKind { var displayName:String { NSLocalizedString(self == .hit ? "击球" : self == .bounce ? "落点" : "回合", comment: "") } }
extension Stroke { var displayName:String { NSLocalizedString("metric.stroke." + rawValue, comment: "") } }
