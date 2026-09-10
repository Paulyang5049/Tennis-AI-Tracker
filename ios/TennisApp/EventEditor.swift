import SwiftUI
import TennisCore

struct EventEditor:View {
    @Environment(\.dismiss) private var dismiss
    @State var event:AnalysisEvent
    let duration:Double
    let save:(AnalysisEvent)throws->Void
    @State private var x=""
    @State private var y=""
    @State private var playerID=""
    @State private var error:String?
    var body:some View {
        NavigationStack {
            Form {
                Picker("类型",selection:$event.kind) { ForEach(EventKind.allCases,id:\.self) { Text($0.displayName).tag($0) } }
                TextField("起始秒数",value:$event.start,format:.number).keyboardType(.decimalPad)
                if event.kind == .rally { TextField("结束秒数",value:$event.end,format:.number).keyboardType(.decimalPad) }
                TextField("球员 ID（可留空）",text:$playerID).keyboardType(.numberPad)
                if event.kind == .hit { Picker("动作",selection:$event.stroke) { ForEach(Stroke.allCases,id:\.self) { Text($0.displayName).tag($0) } } }
                if event.kind == .bounce {
                    Text("落点以双打场地米数记录，左上角为原点；无法确认时留空。")
                    TextField("横向 0–10.97 米",text:$x).keyboardType(.decimalPad)
                    TextField("纵向 0–23.77 米",text:$y).keyboardType(.decimalPad)
                }
                Toggle("已复核",isOn:$event.reviewed); Toggle("排除此事件",isOn:$event.excluded); Toggle("收藏",isOn:$event.favorite)
                if let error { Text(error).foregroundStyle(.red) }
            }.navigationTitle("编辑事件")
            .toolbar {
                ToolbarItem(placement:.cancellationAction) { Button("取消") { dismiss() } }
                ToolbarItem(placement:.confirmationAction) { Button("保存") {
                    do {
                        if event.kind != .rally { event.end=event.start }
                        if !playerID.isEmpty && Int(playerID)==nil { throw PackageError.invalid("球员 ID 应为整数") }
                        event.playerId=Int(playerID)
                        if event.kind == .bounce && (!x.isEmpty || !y.isEmpty) {
                            guard let px=Double(x),let py=Double(y),px.isFinite,py.isFinite else { throw PackageError.invalid("请填写两个有效落点坐标") }
                            event.position=[px,py]
                        } else { event.position=nil }
                        try event.validate(duration:duration); try save(event); dismiss()
                    } catch { self.error=error.localizedDescription }
                } }
            }.onAppear { playerID=event.playerId.map(String.init) ?? ""; if let p=event.position { x=String(p[0]); y=String(p[1]) } }
        }
    }
}

extension EventKind { var displayName:String { switch self { case .hit: return "击球"; case .bounce: return "落点"; case .rally: return "回合" } } }
extension Stroke { var displayName:String { switch self { case .serve:return "发球"; case .forehand:return "正手"; case .backhand:return "反手"; case .volley:return "截击"; case .overhead:return "高压"; case .unknown:return "未确定" } } }
