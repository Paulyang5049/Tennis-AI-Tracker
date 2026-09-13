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
public struct RuntimeState: Codable, Equatable, Sendable {
    public var nextFrame = 0; public var lastTimestamp: Double = -1
    public var ball=BallTracker(); public var players=PlayerTracker(); public var temporal=TemporalEvents()
    public var scene=0
    public init() {}
}
public struct ResumeIdentity: Codable, Equatable, Sendable {
    public var mediaSha256: String; public var settings: AnalysisSettings
    public var modelProvenance: [String:String]; public var runtime = "tennis-ios-2.0.0"
    public init(manifest: Manifest) { mediaSha256=manifest.media.sha256; settings=manifest.settings; modelProvenance=manifest.modelProvenance }
}
