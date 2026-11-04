// swift-tools-version: 6.0
import PackageDescription
let package = Package(name: "TennisCore", platforms: [.macOS(.v13), .iOS("26.0")],
    products: [.library(name: "TennisCore", targets: ["TennisCore"])],
    targets: [.systemLibrary(name: "CSQLite", pkgConfig: "sqlite3"),
              .target(name: "TennisCore", dependencies: ["CSQLite"]),
              .testTarget(name: "TennisCoreTests", dependencies: ["TennisCore"])],
    swiftLanguageModes: [.v5])
