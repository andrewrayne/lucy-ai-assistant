// swift-tools-version:5.10
// Jarvis: Lucy's menu bar app for the Mac. Build with ../scripts/build_jarvis.sh (no Xcode needed).
import PackageDescription

let package = Package(
    name: "Jarvis",
    platforms: [.macOS("26.0")],  // SpeechAnalyzer (on-device wake word) needs macOS 26
    targets: [
        .executableTarget(name: "Jarvis", path: "Sources/Jarvis")
    ]
)
