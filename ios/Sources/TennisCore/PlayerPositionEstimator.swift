import Foundation
import CryptoKit

public enum PlayerPositionEstimator {
    /// Ground-point estimates from explicitly supplied calibration; never ball projections.
    public static func sample(player: Player, frame: FrameRecord) -> PlayerPosition {
        let ankles = (player.pose ?? []).dropFirst(15).prefix(2).filter { $0.count >= 3 && $0[2] >= 0.6 && $0.allSatisfy(\.isFinite) }
        let image = ankles.count == 2 ? [ankles.reduce(0) { $0 + $1[0] } / 2, ankles.reduce(0) { $0 + $1[1] } / 2] : [(player.box[0] + player.box[2]) / 2, player.box[3]]
        var position: [Double]?, calibration: String?
        if let court = frame.court, court.source == "manual", !frame.cut, !frame.cameraMoving,
           let projected = Homography.project(image, matrix: court.matrix),
           (-4...15).contains(projected[0]), (-8...32).contains(projected[1]) {
            position = projected
            let content = "\(frame.scene):" + court.matrix.flatMap { $0 }.map { String(format: "%.9f", locale: Locale(identifier: "en_US_POSIX"), $0) }.joined(separator: ",")
            calibration = SHA256.hash(data: Data(content.utf8)).map { String(format: "%02x", $0) }.joined()
        }
        let side: String = position.map { $0[1] > 12.485 ? "near" : $0[1] < 11.285 ? "far" : "unknown" } ?? "unknown"
        return PlayerPosition(timestamp: frame.timestamp, scene: frame.scene, trackId: player.id, side: side,
            positionCourtM: position, method: position == nil ? nil : ankles.count == 2 ? "ankles_homography" : "box_bottom_homography",
            reviewed: false, calibrationId: calibration, imagePointPx: image, errorM: nil, roleState: side == "unknown" ? "unknown" : "candidate")
    }
}
