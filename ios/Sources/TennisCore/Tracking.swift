import Foundation

public enum Homography {
    /// Four corners: far-left, far-right, near-left, near-right; all in oriented pixels.
    public static func solve(points: [[Double]]) throws -> [[Double]] {
        guard points.count == 4, points.allSatisfy({ $0.count == 2 && $0.allSatisfy(\.isFinite) }) else { throw PackageError.invalid("Select four court corners") }
        let polygon = [points[0], points[1], points[3], points[2]]
        var signs = [Double]()
        for i in 0..<4 {
            let a = polygon[i], b = polygon[(i+1)%4], c = polygon[(i+2)%4]
            signs.append((b[0]-a[0])*(c[1]-b[1]) - (b[1]-a[1])*(c[0]-b[0]))
        }
        guard signs.allSatisfy({ $0 > 1e-6 }) || signs.allSatisfy({ $0 < -1e-6 }) else { throw PackageError.invalid("Court corners must form a convex quadrilateral in the shown order") }
        let targets = [[0.0,0.0], [10.97,0], [0,23.77], [10.97,23.77]]
        var a = [[Double]]()
        for (p, q) in zip(points, targets) {
            let x=p[0], y=p[1], u=q[0], v=q[1]
            a.append([x,y,1,0,0,0,-u*x,-u*y,u]); a.append([0,0,0,x,y,1,-v*x,-v*y,v])
        }
        for col in 0..<8 {
            let pivot = (col..<8).max { abs(a[$0][col]) < abs(a[$1][col]) }!
            guard abs(a[pivot][col]) > 1e-10 else { throw PackageError.invalid("Court corners are degenerate") }
            a.swapAt(col,pivot); let divisor = a[col][col]
            for j in col...8 { a[col][j] /= divisor }
            for row in 0..<8 where row != col {
                let factor = a[row][col]; for j in col...8 { a[row][j] -= factor*a[col][j] }
            }
        }
        let h = (0..<8).map { a[$0][8] } + [1]
        return [Array(h[0..<3]), Array(h[3..<6]), Array(h[6..<9])]
    }
    public static func project(_ p: [Double], matrix h: [[Double]]) -> [Double]? {
        guard p.count == 2, h.count == 3, h.allSatisfy({ $0.count == 3 }) else { return nil }
        let d = h[2][0]*p[0] + h[2][1]*p[1] + h[2][2]
        guard abs(d) > 1e-10 else { return nil }
        let result = [(h[0][0]*p[0]+h[0][1]*p[1]+h[0][2])/d, (h[1][0]*p[0]+h[1][1]*p[1]+h[1][2])/d]
        return result.allSatisfy(\.isFinite) ? result : nil
    }
}

public struct TimedPoint: Codable, Equatable, Sendable {
    public var time: Double; public var xy: [Double]
    public init(time: Double, xy: [Double]) { self.time = time; self.xy = xy }
}
public struct BallTracker: Codable, Equatable, Sendable {
    public var history: [TimedPoint] = []
    public init() {}
    public mutating func update(candidates: [Detection], time: Double, width: Int, height: Int) -> Ball {
        if let last = history.last, time-last.time > 0.25 { history = [] }
        var prediction = history.last?.xy
        if history.count == 2 {
            let a=history[0], b=history[1], dt=max(0.001,b.time-a.time)
            prediction = zip(a.xy,b.xy).map { $1 + ($1-$0)/dt*(time-b.time) }
        }
        let diagonal = hypot(Double(width),Double(height))
        let ranked: [(Double,Detection)] = candidates.compactMap { candidate in
            guard candidate.box.count == 4 else { return nil }
            var score = candidate.confidence
            if let p = prediction {
                let xy=candidate.center, distance=hypot(xy[0]-p[0],xy[1]-p[1])/diagonal
                if distance > max(0.08,min(0.35,(time-(history.last?.time ?? time))*3)) { return nil }
                score -= 2*distance
            }
            return (score,candidate)
        }
        guard let selected = ranked.max(by: { $0.0 < $1.0 })?.1 else { return Ball() }
        history.append(.init(time: time, xy: selected.center)); history = Array(history.suffix(2))
        return Ball(status: .observed, xy: selected.center, confidence: selected.confidence)
    }
}
public struct PlayerTrack: Codable, Equatable, Sendable {
    public var id: Int; public var box: [Double]; public var lastSeen: Double; public var confidence: Double
}
public struct PlayerTracker: Codable, Equatable, Sendable {
    public var tracks: [PlayerTrack] = []; public var nextId = 1
    public init() {}
    /// Track IDs survive storage segments; occlusion over three seconds may create a new ID.
    /// Manual display-name corrections are supported; identities across long occlusion are not claimed.
    public mutating func update(detections: [Detection], time: Double, count: Int, width: Int, height: Int) -> [Player] {
        tracks.removeAll { time-$0.lastSeen > 3 }
        let candidates = Array(detections.sorted { $0.confidence > $1.confidence }.prefix(count))
        var available = Set(tracks.indices), result = [Player]()
        for d in candidates {
            let c=d.center
            let best = available.min { a,b in
                distance(c, tracks[a].box) < distance(c, tracks[b].box)
            }
            let index: Int
            if let match = best, distance(c,tracks[match].box) < hypot(Double(width),Double(height))*0.15 {
                index=match; available.remove(match); tracks[index].box=d.box; tracks[index].lastSeen=time; tracks[index].confidence=d.confidence
            } else {
                index=tracks.count; tracks.append(.init(id: nextId, box: d.box, lastSeen: time, confidence: d.confidence)); nextId += 1
            }
            result.append(.init(id: tracks[index].id,box: d.box,confidence: d.confidence))
        }
        return result
    }
    private func distance(_ center: [Double], _ box: [Double]) -> Double {
        hypot(center[0]-(box[0]+box[2])/2,center[1]-(box[1]+box[3])/2)
    }
}
public struct TemporalEvents: Codable, Equatable, Sendable {
    public var recent: [TimedPoint] = []; public var rallyStart: Double?; public var lastObserved: Double?
    public var observations = 0; public var lastEventTime: Double = -10
    public init() {}
    public mutating func consume(_ frame: FrameRecord) -> [AnalysisEvent] {
        var events = [AnalysisEvent]()
        if frame.cameraMoving {
            if let rally = finish(scene: frame.cut ? max(0, frame.scene - 1) : frame.scene) { events.append(rally) }
            recent = []; return events
        }
        if frame.cut {
            if let rally=finish(scene: frame.scene-1) { events.append(rally) }; recent=[]
        }
        guard frame.ball.status == .observed, let xy=frame.ball.xy else {
            if let last=lastObserved, frame.timestamp-last > 1.5 {
                if let rally=finish(scene: frame.scene) { events.append(rally) }; recent=[]
            }
            return events
        }
        if let last=lastObserved, frame.timestamp-last > 0.3 { recent=[] }
        if rallyStart == nil { rallyStart=frame.timestamp; observations=0 }
        observations += 1; lastObserved=frame.timestamp
        recent.append(.init(time: frame.timestamp,xy: xy)); recent=Array(recent.suffix(3))
        guard recent.count == 3, frame.timestamp-lastEventTime > 0.25 else { return events }
        let a=recent[0], b=recent[1], c=recent[2]
        let dt0=max(0.001,b.time-a.time), dt1=max(0.001,c.time-b.time)
        let v0=[(b.xy[0]-a.xy[0])/dt0,(b.xy[1]-a.xy[1])/dt0], v1=[(c.xy[0]-b.xy[0])/dt1,(c.xy[1]-b.xy[1])/dt1]
        let speed0=hypot(v0[0],v0[1]), speed1=hypot(v1[0],v1[1])
        guard speed0>40, speed1>40 else { return events }
        let turn=(v0[0]*v1[0]+v0[1]*v1[1])/(speed0*speed1)
        let nearby=frame.players.min { distanceToBox(b.xy,$0.box) < distanceToBox(b.xy,$1.box) }
        var event: AnalysisEvent?
        if turn < 0.25, let player=nearby, distanceToBox(b.xy,player.box) < max(45,(player.box[3]-player.box[1])*0.8) {
            var hit=AnalysisEvent(id: "hit-\(frame.scene)-\(frame.frame-1)",kind: .hit,start: b.time)
            hit.playerId=player.id; event=hit
        } else if v0[1]>50, v1[1]<(-50) {
            // Image-space direction changes are only review candidates, never verified bounces.
            event=AnalysisEvent(id: "bounce-\(frame.scene)-\(frame.frame-1)",kind: .bounce,start: b.time)
            // A trajectory turn is not proof of ground contact. Position stays unknown
            // until the bounce and its observed image point are reviewed.
        }
        if var event {
            event.scene=frame.scene; event.provenance="automatic"; event.reviewed=false
            events.append(event); lastEventTime=b.time
        }
        return events
    }
    public mutating func finish(scene: Int) -> AnalysisEvent? {
        defer { rallyStart=nil; lastObserved=nil; observations=0 }
        guard let start=rallyStart, let end=lastObserved, end-start>=1, observations>=5 else { return nil }
        var event=AnalysisEvent(id: "rally-\(scene)-\(Int((start*1000).rounded()))",kind: .rally,start: start,end: end)
        event.scene=max(0,scene); event.provenance="automatic"; event.reviewed=false; return event
    }
    private func distanceToBox(_ p:[Double],_ b:[Double])->Double {
        hypot(max(b[0]-p[0],0,p[0]-b[2]),max(b[1]-p[1],0,p[1]-b[3]))
    }
}
/// Opt-in, gap-tolerant hit candidates; mirrors Python's `contact-v2` and is not validated
/// against labelled contacts. A visit is a run of observed samples inside one player's hitting
/// region, tolerating gaps up to `maxGap`; it becomes a hit only when a later observed sample
/// crosses the line between the players in the outgoing direction. Interpolated samples are
/// never used. Bounces still come from the baseline turn rule.
public struct ContactEvents: Codable, Equatable, Sendable {
    public static let version = "contact-v2"
    struct Sample: Codable, Equatable, Sendable { var time: Double; var frame: Int; var xy: [Double]; var distance = 0.0 }
    struct Visit: Codable, Equatable, Sendable { var player: Int; var near: Bool; var line: Double; var samples: [Sample] }
    struct Rally: Codable, Equatable, Sendable { var start: Double; var end: Double; var scene: Int; var frame: Int; var hits = 0 }
    var maxGap = 0.4, departure = 1.2, cooldown = 0.35, rallyGap = 2.0
    var bounces = TemporalEvents()
    var visit: Visit?; var pending: [Visit] = []; var hitTimes: [Double] = []
    var rally: Rally?; var scene: Int?; var lastObserved: Double?
    public init() {}

    public mutating func consume(_ frame: FrameRecord) -> [AnalysisEvent] {
        var result = bounces.consume(frame).filter { $0.kind == .bounce }
        if scene != frame.scene || frame.cut || frame.cameraMoving {
            result += closeRally(); visit = nil; pending = []; lastObserved = nil
        }
        scene = frame.scene
        if let r = rally, frame.timestamp - r.end > rallyGap { result += closeRally() }
        guard frame.ball.status == .observed, let xy = frame.ball.xy, !frame.cameraMoving else { return result }
        if let last = lastObserved, frame.timestamp - last > maxGap { closeVisit() }
        lastObserved = frame.timestamp
        rally?.end = frame.timestamp
        let found = owner(xy, Array(frame.players.prefix(4)))
        let sample = Sample(time: frame.timestamp, frame: frame.frame, xy: xy)
        if found == nil || (visit != nil && visit?.player != found?.player) { closeVisit() }
        result += confirm(sample, scene: frame.scene)
        if let found {
            if visit == nil { visit = Visit(player: found.player, near: found.near, line: found.line, samples: []) }
            // Bound a long visit, such as a ball held before a serve.
            var kept = Array(visit!.samples.suffix(39)); var owned = sample; owned.distance = found.distance
            kept.append(owned); visit!.samples = kept
        }
        return result
    }

    public mutating func finish() -> [AnalysisEvent] { closeRally() }

    private mutating func closeVisit() {
        if let v = visit, v.samples.count >= 2 {
            // A later visit by the same player supersedes an unconfirmed one (a pre-serve bounce or toss).
            pending.removeAll { $0.player == v.player }; pending.append(v)
        }
        visit = nil
    }

    private mutating func confirm(_ sample: Sample, scene: Int) -> [AnalysisEvent] {
        var result = [AnalysisEvent](), remaining = [Visit]()
        for v in pending {
            let y = sample.xy[1]
            if v.near ? y <= v.line : y >= v.line { result += hit(v, departure: sample, scene: scene) }
            else if sample.time - (v.samples.last?.time ?? sample.time) <= departure { remaining.append(v) }
        }
        pending = remaining
        return result
    }

    private mutating func hit(_ v: Visit, departure sample: Sample, scene: Int) -> [AnalysisEvent] {
        guard let lastTime = v.samples.last?.time else { return [] }
        let offset = v.samples.firstIndex { lastTime - $0.time <= 0.6 } ?? 0
        let recent = v.samples[offset...]
        guard let closest = recent.min(by: { $0.distance < $1.distance }),
              let index = v.samples.firstIndex(of: closest) else { return [] }
        let following = index + 1 < v.samples.count ? v.samples[index + 1] : sample
        var time = closest.time
        // Contact fell inside unobserved frames; both bounds are observations.
        if following.time - time > 0.07 { time = (time + following.time) / 2 }
        if hitTimes.contains(where: { abs(time - $0) < cooldown }) { return [] }
        hitTimes = Array((hitTimes + [time]).suffix(4))
        if rally == nil { rally = Rally(start: time, end: sample.time, scene: scene, frame: closest.frame) }
        rally?.hits += 1
        var event = AnalysisEvent(id: "hit-\(scene)-\(closest.frame)", kind: .hit, start: time)
        event.scene = scene; event.playerId = v.player; event.provenance = "automatic"; event.reviewed = false
        return [event]
    }

    private mutating func closeRally() -> [AnalysisEvent] {
        defer { rally = nil }
        guard let r = rally, r.hits >= 2 else { return [] }
        var event = AnalysisEvent(id: "rally-\(r.scene)-\(r.frame)", kind: .rally, start: max(0, r.start - 0.5), end: r.end)
        event.scene = r.scene; event.provenance = "automatic"; event.reviewed = false
        return [event]
    }

    /// Nearest player whose hitting region holds the ball, with the side split line.
    private func owner(_ point: [Double], _ players: [Player]) -> (player: Int, near: Bool, line: Double, distance: Double)? {
        let bottoms = players.map { $0.box[3] }.sorted()
        var best: (Double, Player)?
        for player in players { if let d = Self.reach(point, player), best == nil || d < best!.0 { best = (d, player) } }
        guard let (distance, player) = best, let far = bottoms.first, let near = bottoms.last, bottoms.count >= 2, near - far >= 1 else { return nil }
        let isNear = player.box[3] >= (far + near) / 2
        // In a fixed full-court view the net lies about a fifth of the feet span below the far player.
        return (player.id, isNear, far + (isNear ? 0.2 : 0.35) * (near - far), distance)
    }

    /// Normalized distance to a player's wrists, or nil outside the hitting region.
    static func reach(_ point: [Double], _ player: Player) -> Double? {
        let b = player.box, height = max(1, b[3] - b[1]), x = point[0], y = point[1]
        guard b[0] - 0.6 * height <= x, x <= b[2] + 0.6 * height, b[1] - 0.5 * height <= y, y <= b[3] else { return nil }
        let pose = player.pose ?? []
        let joints = (9...10).compactMap { i -> [Double]? in
            i < pose.count && pose[i].count == 3 && pose[i][2] >= 0.3 ? Array(pose[i][0..<2]) : nil
        }
        let anchors = joints.isEmpty ? [[(b[0] + b[2]) / 2, b[1] + 0.4 * height]] : joints
        return anchors.map { hypot(x - $0[0], y - $0[1]) }.min()! / height
    }
}
public struct RuntimeState: Codable, Equatable, Sendable {
    public var nextFrame = 0; public var lastTimestamp: Double = -1
    public var ball=BallTracker(); public var players=PlayerTracker(); public var temporal=TemporalEvents()
    public var scene=0
    /// Present only for analyses that opted into `contact-v2`; older checkpoints decode as nil.
    public var contact: ContactEvents?
    public init() {}
}
public struct ResumeIdentity: Codable, Equatable, Sendable {
    public var mediaSha256: String; public var settings: AnalysisSettings
    public var modelProvenance: [String:String]; public var runtime = "tennis-ios-2.0.0"
    public init(manifest: Manifest) { mediaSha256=manifest.media.sha256; settings=manifest.settings; modelProvenance=manifest.modelProvenance }
}
