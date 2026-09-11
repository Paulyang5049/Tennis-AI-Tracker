import SwiftUI
import AVKit
import Combine
import UniformTypeIdentifiers
import TennisCore

@main struct TennisApp:App {
    var body:some Scene { WindowGroup { LibraryView() } }
}
struct LibraryView:View {
    @State private var items=[MatchItem]()
    @State private var importing=false
    @State private var package=false
    @State private var busy=false
    @State private var players=2
    @State private var error:String?
    var body:some View {
        NavigationStack {
            List {
                Section("导入设置") { Picker("球员人数",selection:$players) { Text("单打").tag(2); Text("双打").tag(4) } }
                Section {
                    ForEach(items) { item in
                        NavigationLink { ReviewView(item:item) } label: {
                            VStack(alignment:.leading) { Text(item.title); Text("\(item.manifest.media.duration,specifier:"%.0f") 秒 · \(ByteCountFormatter.string(fromByteCount:LocalLibrary.diskUsage(item),countStyle:.file))").font(.caption) }
                        }
                    }.onDelete { indices in perform { for index in indices { try LocalLibrary.remove(items[index]) }; try reload() } }
                }
                Text("所有视频与分析留在本机。自动事件为待复核候选；统计仅使用已确认事件。分析时请保持应用在前台。").font(.footnote)
            }.navigationTitle("网球复盘")
            .toolbar { Menu("导入") { Button("视频") { package=false; importing=true }; Button("分析文件夹") { package=true; importing=true } }.disabled(busy) }
            .overlay { if busy { ProgressView("正在导入…") } }
            .fileImporter(isPresented:$importing,allowedContentTypes:package ? [.folder] : [.movie]) { result in
                guard case .success(let url)=result else { return }
                busy=true
                Task { do { _=try await LibraryImporter().importFile(url,package:package,players:players); try reload() } catch { self.error=error.localizedDescription }; busy=false }
            }
            .task { perform { try reload() } }
            .alert("提示",isPresented:Binding(get:{error != nil},set:{if !$0 { error=nil }})) { Button("好") { error=nil } } message: { Text(error ?? "") }
        }
    }
    func reload()throws { items=try LocalLibrary.list() }
    func perform(_ action:()throws->Void) { do { try action() } catch { self.error=error.localizedDescription } }
}

struct ReviewView:View {
    let item:MatchItem
    @Environment(\.scenePhase) private var scenePhase
    @State private var player=AVPlayer()
    @State private var store:AnalysisStore?
    @State private var events=[AnalysisEvent]()
    @State private var current=0.0
    @State private var frame:FrameRecord?
    @State private var trail=[FrameRecord]()
        @State private var task:Task<Void,Never>?
    @State private var progress=0.0
    @State private var error:String?
    @State private var editing:AnalysisEvent?
    @State private var calibrating=false
    @State private var corners=[[Double]]()
    @State private var exportURL:URL?
    @State private var exporting=false
    @State private var showOverlay=true
    @State private var name=""
    @State private var selectedPlayer=1
    @State private var migratedItem: MatchItem?
    private let timer=Timer.publish(every:0.15,on:.main,in:.common).autoconnect()
    var body:some View {
        ScrollView {
            VStack(spacing:14) {
                ZStack {
                    VideoPlayer(player:player)
                    if showOverlay || calibrating {
                        GeometryReader { geometry in
                            Canvas { context,size in
                                let sx=size.width/Double(item.manifest.media.width),sy=size.height/Double(item.manifest.media.height)
                                for p in frame?.players ?? [] {
                                    let rect=CGRect(x:p.box[0]*sx,y:p.box[1]*sy,width:(p.box[2]-p.box[0])*sx,height:(p.box[3]-p.box[1])*sy)
                                    context.stroke(Path(rect),with:.color(.green),lineWidth:2)
                                    context.draw(Text(p.label ?? "P\(p.id)").foregroundStyle(.green),at:CGPoint(x:rect.midX,y:rect.minY+10))
                                }
                                var path=Path(); var connected=false
                                for f in trail {
                                    if let xy=f.ball.xy { let p=CGPoint(x:xy[0]*sx,y:xy[1]*sy); if connected { path.addLine(to:p) } else { path.move(to:p) }; connected=true } else { connected=false }
                                }
                                context.stroke(path,with:.color(.yellow),lineWidth:2)
                                for (i,p) in corners.enumerated() { context.draw(Text("\(i+1)").foregroundStyle(.red),at:CGPoint(x:p[0]*sx,y:p[1]*sy)) }
                            }.contentShape(Rectangle()).onTapGesture { point in
                                if calibrating && corners.count<4 { corners.append([point.x/geometry.size.width*Double(item.manifest.media.width),point.y/geometry.size.height*Double(item.manifest.media.height)]) }
                            }.allowsHitTesting(calibrating)
                        }
                    }
                }.aspectRatio(Double(item.manifest.media.width)/Double(item.manifest.media.height),contentMode:.fit)
                Slider(value:Binding(get:{current},set:{seek($0)}),in:0...item.manifest.media.duration)
                HStack {
                    Button("上一帧") { step(false) }; Button("播放") { player.play() }; Button("暂停") { player.pause() }; Button("下一帧") { step(true) }
                    Menu("速度") { ForEach([0.25,0.5,1.0,2.0],id:\.self) { rate in Button("\(rate, specifier:"%.2g")×") { player.rate=Float(rate) } } }
                }.font(.caption)
                Toggle("球员与轨迹",isOn:$showOverlay)
                if task != nil { ProgressView(value:progress); Button("暂停分析（保留进度）") { task?.cancel() } }
                else { Button("开始 / 继续离线分析") { start() } }
                if calibrating {
                    Text("暂停画面后，依次点击双打场地：远左、远右、近左、近右。当前 \(corners.count)/4")
                    HStack { Button("重选") { corners=[] }; Button("保存校准") { saveCourt() }.disabled(corners.count != 4); Button("取消") { calibrating=false; corners=[] } }
                } else { Button("人工校准场地") { player.pause(); corners=[]; calibrating=true } }
                HStack { Stepper("球员 ID \(selectedPlayer)",value:$selectedPlayer,in:1...1000); TextField("显示名称",text:$name); Button("保存") { saveName() } }
                HStack { Button("添加击球") { editing=AnalysisEvent(kind:.hit,start:current) }; Button("添加落点") { editing=AnalysisEvent(kind:.bounce,start:current) }; Button("添加回合") { editing=AnalysisEvent(kind:.rally,start:current,end:min(current+1,item.manifest.media.duration)) } }
                let stats=VerifiedStatistics(events:events)
                Text("已确认：击球 \(stats.hits) · 落点 \(stats.bounces) · 回合 \(stats.rallies)")
                ForEach(events) { event in
                    HStack {
                        Button("\(event.start, specifier:"%.2f")s · \(event.kind.displayName)\(event.reviewed ? " ✓" : " 待复核")\(event.excluded ? " 已排除" : "")") { seek(event.start) }
                        Spacer(); Button("编辑") { editing=event }
                        Button("导出") { export(event) }.disabled(exporting)
                    }.font(.caption)
                }
                if let exportURL { ShareLink("分享片段",item:exportURL) }
                Button("更新可互操作分析文件") { perform { guard let store else { return }; var m=try PackageIO.load(item.folder); m.status=try store.status(); try store.export(to:item.folder,manifest:m) } }
                if item.manifest.schemaVersion == 2 && item.manifest.status == .complete {
                    Button("另存为新版分析（保留原比赛）") { perform { migratedItem = try LocalLibrary.saveAsV3(item) } }
                }
            }.padding()
        }.navigationTitle(item.title)
        .navigationDestination(item: $migratedItem) { ReviewView(item: $0) }
        .task { perform { player.replaceCurrentItem(with:AVPlayerItem(url:try PackageIO.asset(item.manifest.media.path,in:item.folder))); try openStore() } }
        .onReceive(timer) { _ in
            let time=player.currentTime().seconds-item.manifest.media.origin
            if time.isFinite { current=max(0,time); refreshFrame() }
        }
        .onDisappear { player.pause(); task?.cancel() }
        .onChange(of:scenePhase) { _,phase in if phase != .active { task?.cancel() } }
        .sheet(item:$editing) { event in EventEditor(event:event,duration:item.manifest.media.duration) { updated in guard let store else { throw PackageError.invalid("请先开始分析以建立记录") }; try store.saveEvent(updated,duration:item.manifest.media.duration); try refresh() } }
        .alert("提示",isPresented:Binding(get:{error != nil},set:{if !$0 { error=nil }})) { Button("好") { error=nil } } message: { Text(error ?? "") }
    }
    func perform(_ action:()throws->Void) { do { try action() } catch { self.error=error.localizedDescription } }
    func openStore()throws {
        let m=try PackageIO.load(item.folder)
        // Do not create a resume identity before the detector is chosen.
        if FileManager.default.fileExists(atPath:item.folder.appendingPathComponent("analysis.sqlite").path) || !m.modelProvenance.isEmpty {
            store=try AnalysisStore(url:item.folder.appendingPathComponent("analysis.sqlite"),identity:ResumeIdentity(manifest:m)); try refresh()
        }
    }
    func refresh()throws { events=try store?.events() ?? []; refreshFrame() }
    func refreshFrame() {
        frame=try? store?.frame(at:current); trail=(try? store?.trajectory(ending:current)) ?? []
        if var value=frame, let labels=try? store?.corrections().labels[String(value.scene)] {
            for i in value.players.indices { value.players[i].label=labels[String(value.players[i].id)] }; frame=value
        }
    }
    func seek(_ time:Double) { current=time; player.seek(to:CMTime(seconds:time+item.manifest.media.origin,preferredTimescale:60000),toleranceBefore:.zero,toleranceAfter:.zero); refreshFrame() }
    func step(_ forward:Bool) { perform { if let time=try store?.neighboringTime(current,forward:forward) { seek(time) } else { player.currentItem?.step(byCount:forward ? 1 : -1) } } }
    func start() {
        task=Task {
            do { try await AnalysisEngine().run(item:item) { value in Task { @MainActor in progress=value; if store == nil { perform { try openStore() } } } }; try openStore() }
            catch is CancellationError { perform { try openStore() } }
            catch { self.error=error.localizedDescription; perform { try openStore() } }
            task=nil
        }
    }
    func saveCourt() { perform { _=try Court(points:corners); guard let store else { throw PackageError.invalid("请先开始分析以建立记录") }; var c=try store.corrections(); guard let frame else { throw PackageError.invalid("请先显示一个已分析画面") }; c.court[String(frame.frame)]=corners; try store.saveCorrections(c); calibrating=false } }
    func saveName() { perform { guard let store else { throw PackageError.invalid("请先开始分析") }; var c=try store.corrections(); c.labels[String(frame?.scene ?? 0),default:[:]][String(selectedPlayer)]=name; try store.saveCorrections(c); refreshFrame() } }
    func export(_ event:AnalysisEvent) { exporting=true; Task { do { exportURL=try await ClipExporter.export(item:item,event:event) } catch { self.error=error.localizedDescription }; exporting=false } }
}
