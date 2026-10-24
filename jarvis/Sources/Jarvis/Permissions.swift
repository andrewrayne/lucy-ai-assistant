import AVFoundation
import AppKit
import ApplicationServices
import Speech

/// The macOS permissions Jarvis needs, and a way to ask for the missing ones.
enum Permissions {
    static var microphone: Bool { AVCaptureDevice.authorizationStatus(for: .audio) == .authorized }
    static var speech: Bool { SFSpeechRecognizer.authorizationStatus() == .authorized }
    static var screen: Bool { CGPreflightScreenCaptureAccess() }
    static var accessibility: Bool { AXIsProcessTrusted() }

    /// Ask for everything that's still missing. macOS shows its own prompts.
    static func requestMissing(_ done: @escaping () -> Void) {
        AVCaptureDevice.requestAccess(for: .audio) { _ in
            SFSpeechRecognizer.requestAuthorization { _ in
                if !screen { CGRequestScreenCaptureAccess() }
                if !accessibility {
                    let key = kAXTrustedCheckOptionPrompt.takeUnretainedValue() as String
                    _ = AXIsProcessTrustedWithOptions([key: true] as CFDictionary)
                }
                DispatchQueue.main.async(execute: done)
            }
        }
    }

    static var summary: String {
        func line(_ name: String, _ ok: Bool) -> String { "\(ok ? "✅" : "❌") \(name)" }
        return [
            line("Microphone (to hear you)", microphone),
            line("Speech Recognition (for “\(WakeWord.wakeWord)”)", speech),
            line("Screen Recording (to see the screen)", screen),
            line("Accessibility (to click and type)", accessibility),
        ].joined(separator: "\n")
    }

    static func openSettings(_ pane: String) {
        if let url = URL(string: "x-apple.systempreferences:com.apple.preference.security?\(pane)") {
            NSWorkspace.shared.open(url)
        }
    }
}
