import AppKit
import ApplicationServices
import ScreenCaptureKit

/// Things the server can ask the Mac to do. Each request is
/// {"type": "device", "id": "...", "action": "...", ...} and gets one answer dictionary back.
/// Coordinates are on a 0-1000 grid over the main display (same grid as the screenshot).
enum Device {
    static func handle(_ request: [String: Any]) async -> [String: Any] {
        let action = request["action"] as? String ?? ""
        do {
            switch action {
            case "screenshot": return try await screenshot()
            case "click":
                click(at: point(request), right: request["button"] as? String == "right", count: request["count"] as? Int ?? 1)
            case "type": type(request["text"] as? String ?? "")
            case "key": try key(request["keys"] as? String ?? "")
            case "scroll": scroll(at: point(request), lines: request["dy"] as? Int ?? -3)
            case "open": return try await open(request["target"] as? String ?? "")
            case "quit_app": return try quitApp(request["app"] as? String ?? "")
            case "volume":
                return try await MainActor.run { try volume(request["command"] as? String ?? "", level: request["level"] as? Int ?? 50) }
            case "media": return try await MainActor.run { try media(request["command"] as? String ?? "toggle") }
            case "system": return try system(request["command"] as? String ?? "")
            case "spotify":
                return try await MainActor.run {
                    try spotify(request["command"] as? String ?? "", volume: request["volume"] as? Int ?? 50)
                }
            default: return ["ok": false, "error": "Unknown action \(action)"]
            }
            return ["ok": true]
        } catch {
            return ["ok": false, "error": error.localizedDescription]
        }
    }

    struct Failure: LocalizedError {
        let errorDescription: String?
        init(_ message: String) { errorDescription = message }
    }

    // MARK: Screen

    static func screenshot() async throws -> [String: Any] {
        let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: true)
        guard let display = content.displays.first(where: { $0.displayID == CGMainDisplayID() }) ?? content.displays.first
        else { throw Failure("No display found") }
        let scale = min(1.0, 1440.0 / Double(display.width))
        let config = SCStreamConfiguration()
        config.width = Int(Double(display.width) * scale)
        config.height = Int(Double(display.height) * scale)
        config.showsCursor = true
        let filter = SCContentFilter(display: display, excludingWindows: [])
        let image = try await SCScreenshotManager.captureImage(contentFilter: filter, configuration: config)
        guard let jpeg = NSBitmapImageRep(cgImage: image).representation(using: .jpeg, properties: [.compressionFactor: 0.7])
        else { throw Failure("Could not encode the screenshot") }
        let app = NSWorkspace.shared.frontmostApplication?.localizedName ?? ""
        return ["ok": true, "image": jpeg.base64EncodedString(), "width": image.width, "height": image.height, "frontmost_app": app]
    }

    // MARK: Mouse and keyboard (needs Accessibility permission)

    private static let source = CGEventSource(stateID: .hidSystemState)

    static func point(_ request: [String: Any]) -> CGPoint {
        let bounds = CGDisplayBounds(CGMainDisplayID())
        let x = Double(request["x"] as? Int ?? 500) / 1000
        let y = Double(request["y"] as? Int ?? 500) / 1000
        return CGPoint(x: bounds.minX + x * bounds.width, y: bounds.minY + y * bounds.height)
    }

    static func click(at point: CGPoint, right: Bool, count: Int) {
        let button: CGMouseButton = right ? .right : .left
        CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: button)?
            .post(tap: .cghidEventTap)
        usleep(80_000)
        for n in 1...max(1, min(count, 3)) {
            for type: CGEventType in right ? [.rightMouseDown, .rightMouseUp] : [.leftMouseDown, .leftMouseUp] {
                let event = CGEvent(mouseEventSource: source, mouseType: type, mouseCursorPosition: point, mouseButton: button)
                event?.setIntegerValueField(.mouseEventClickState, value: Int64(n))
                event?.post(tap: .cghidEventTap)
                usleep(30_000)
            }
            usleep(60_000)
        }
    }

    static func type(_ text: String) {
        let lines = text.components(separatedBy: "\n")
        for (index, line) in lines.enumerated() {
            let units = Array(line.utf16)
            var start = 0
            while start < units.count {
                let chunk = Array(units[start..<min(start + 16, units.count)])
                for down in [true, false] {
                    let event = CGEvent(keyboardEventSource: source, virtualKey: 0, keyDown: down)
                    event?.keyboardSetUnicodeString(stringLength: chunk.count, unicodeString: chunk)
                    event?.post(tap: .cghidEventTap)
                }
                usleep(25_000)
                start += 16
            }
            if index < lines.count - 1 { press(36, flags: []) }  // Return between lines
        }
    }

    static func key(_ combo: String) throws {
        var flags: CGEventFlags = []
        var code: CGKeyCode?
        for part in combo.lowercased().split(separator: "+").map({ $0.trimmingCharacters(in: .whitespaces) }) {
            switch part {
            case "cmd", "command": flags.insert(.maskCommand)
            case "shift": flags.insert(.maskShift)
            case "alt", "option", "opt": flags.insert(.maskAlternate)
            case "ctrl", "control": flags.insert(.maskControl)
            case "fn": flags.insert(.maskSecondaryFn)
            default:
                guard let c = keyCodes[part] else { throw Failure("Unknown key \(part)") }
                code = c
            }
        }
        guard let code else { throw Failure("No key in \(combo)") }
        press(code, flags: flags)
    }

    private static func press(_ code: CGKeyCode, flags: CGEventFlags) {
        for down in [true, false] {
            let event = CGEvent(keyboardEventSource: source, virtualKey: code, keyDown: down)
            event?.flags = flags
            event?.post(tap: .cghidEventTap)
            usleep(20_000)
        }
    }

    static func scroll(at point: CGPoint, lines: Int) {
        CGEvent(mouseEventSource: source, mouseType: .mouseMoved, mouseCursorPosition: point, mouseButton: .left)?
            .post(tap: .cghidEventTap)
        for _ in 0..<min(abs(lines), 20) {
            CGEvent(scrollWheelEvent2Source: source, units: .line, wheelCount: 1, wheel1: lines < 0 ? -3 : 3, wheel2: 0, wheel3: 0)?
                .post(tap: .cghidEventTap)
            usleep(15_000)
        }
    }

    private static let keyCodes: [String: CGKeyCode] = [
        "a": 0, "s": 1, "d": 2, "f": 3, "h": 4, "g": 5, "z": 6, "x": 7, "c": 8, "v": 9, "b": 11, "q": 12,
        "w": 13, "e": 14, "r": 15, "y": 16, "t": 17, "1": 18, "2": 19, "3": 20, "4": 21, "6": 22, "5": 23,
        "=": 24, "9": 25, "7": 26, "-": 27, "8": 28, "0": 29, "]": 30, "o": 31, "u": 32, "[": 33, "i": 34,
        "p": 35, "l": 37, "j": 38, "'": 39, "k": 40, ";": 41, "\\": 42, ",": 43, "/": 44, "n": 45, "m": 46,
        ".": 47, "`": 50,
        "return": 36, "enter": 36, "tab": 48, "space": 49, "delete": 51, "backspace": 51, "esc": 53,
        "escape": 53, "forwarddelete": 117, "home": 115, "end": 119, "pageup": 116, "pagedown": 121,
        "left": 123, "right": 124, "down": 125, "up": 126,
        "f1": 122, "f2": 120, "f3": 99, "f4": 118, "f5": 96, "f6": 97, "f7": 98, "f8": 100, "f9": 101,
        "f10": 109, "f11": 103, "f12": 111,
    ]

    // MARK: Apps, links and files

    static func open(_ target: String) async throws -> [String: Any] {
        let target = target.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !target.isEmpty else { throw Failure("Nothing to open") }
        if target.contains("://") || target.hasPrefix("spotify:") || target.hasPrefix("mailto:") {
            let encoded = target.addingPercentEncoding(withAllowedCharacters: .urlFragmentAllowed.union(["%", "#"])) ?? target
            guard let url = URL(string: encoded), NSWorkspace.shared.open(url) else { throw Failure("Could not open \(target)") }
            return ["ok": true, "opened": target]
        }
        if target.hasPrefix("/") || target.hasPrefix("~") {
            let path = (target as NSString).expandingTildeInPath
            guard FileManager.default.fileExists(atPath: path) else { throw Failure("No such file: \(target)") }
            NSWorkspace.shared.open(URL(fileURLWithPath: path))
            return ["ok": true, "opened": path]
        }
        if target.contains("."), !target.contains(" "), let url = URL(string: "https://\(target)") {
            NSWorkspace.shared.open(url)
            return ["ok": true, "opened": url.absoluteString]
        }
        // An app by name, e.g. "Safari", "Visual Studio Code".
        let process = Process()
        process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
        process.arguments = ["-a", target]
        try process.run()
        process.waitUntilExit()
        guard process.terminationStatus == 0 else { throw Failure("No app called \(target)") }
        // Wait (up to 5 s) until it's really running and in front, and report what actually happened.
        for _ in 0..<25 {
            if let front = NSWorkspace.shared.frontmostApplication?.localizedName,
               front.localizedCaseInsensitiveContains(target) || target.localizedCaseInsensitiveContains(front) {
                return ["ok": true, "opened": front, "state": "running, in front"]
            }
            try await Task.sleep(nanoseconds: 200_000_000)
        }
        let running = NSWorkspace.shared.runningApplications.contains {
            $0.localizedName?.localizedCaseInsensitiveContains(target) == true
        }
        return ["ok": running, "opened": target, "state": running ? "running, not in front" : "did not start"]
    }

    // MARK: Spotify (AppleScript: works with free accounts, needs the Spotify app)

    @MainActor
    static func spotify(_ command: String, volume: Int) throws -> [String: Any] {
        let script: String
        switch command {
        case "play": script = "tell application \"Spotify\" to play"
        case "pause": script = "tell application \"Spotify\" to pause"
        case "next": script = "tell application \"Spotify\" to next track"
        case "previous": script = "tell application \"Spotify\" to previous track"
        case "volume": script = "tell application \"Spotify\" to set sound volume to \(max(0, min(100, volume)))"
        case "now_playing":
            script = """
            tell application "Spotify"
                if player state is playing then
                    return (name of current track) & " by " & (artist of current track)
                else
                    return "Nothing is playing"
                end if
            end tell
            """
        default: throw Failure("Unknown Spotify command \(command)")
        }
        var error: NSDictionary?
        let result = NSAppleScript(source: script)?.executeAndReturnError(&error)
        if let error { throw Failure(error[NSAppleScript.errorMessage] as? String ?? "Spotify didn't respond") }
        return ["ok": true, "result": result?.stringValue ?? "done"]
    }

    // MARK: Apps, volume, media, system

    static func quitApp(_ name: String) throws -> [String: Any] {
        let apps = NSWorkspace.shared.runningApplications.filter {
            $0.activationPolicy == .regular && $0.localizedName?.localizedCaseInsensitiveContains(name) == true
        }
        guard !apps.isEmpty else { throw Failure("\(name) isn't running") }
        apps.forEach { $0.terminate() }
        return ["ok": true, "quit": apps.compactMap(\.localizedName)]
    }

    @MainActor
    static func volume(_ command: String, level: Int) throws -> [String: Any] {
        let script: String
        switch command {
        case "up": script = "set volume output volume ((output volume of (get volume settings)) + 10)"
        case "down": script = "set volume output volume ((output volume of (get volume settings)) - 10)"
        case "mute": script = "set volume output muted true"
        case "unmute": script = "set volume output muted false"
        case "set": script = "set volume output volume \(max(0, min(100, level)))"
        default: throw Failure("Unknown volume command \(command)")
        }
        try runAppleScript(script)
        let now = try runAppleScript("output volume of (get volume settings)")
        return ["ok": true, "volume": Int(now) ?? -1]
    }

    /// Play/pause/next/previous: Spotify or Music if running (AppleScript), otherwise the media keys.
    @MainActor
    static func media(_ command: String) throws -> [String: Any] {
        let running = Set(NSWorkspace.shared.runningApplications.compactMap(\.localizedName))
        for app in ["Spotify", "Music"] where running.contains(app) {
            let verb: String
            switch command {
            case "play": verb = "play"
            case "pause": verb = "pause"
            case "next": verb = "next track"
            case "previous": verb = "previous track"
            default: verb = "playpause"
            }
            try runAppleScript("tell application \"\(app)\" to \(verb)")
            return ["ok": true, "app": app, "done": command]
        }
        let key: Int32 = command == "next" ? 17 : command == "previous" ? 18 : 16  // NX_KEYTYPE_*
        postMediaKey(key)
        return ["ok": true, "app": "media keys", "done": command]
    }

    private static func postMediaKey(_ key: Int32) {
        for down in [true, false] {
            let flags = NSEvent.ModifierFlags(rawValue: down ? 0xA00 : 0xB00)
            let data1 = Int((key << 16) | ((down ? 0xA : 0xB) << 8))
            NSEvent.otherEvent(with: .systemDefined, location: .zero, modifierFlags: flags, timestamp: 0,
                               windowNumber: 0, context: nil, subtype: 8, data1: data1, data2: -1)?
                .cgEvent?.post(tap: .cghidEventTap)
        }
    }

    static func system(_ command: String) throws -> [String: Any] {
        switch command {
        case "lock":
            press(12, flags: [.maskCommand, .maskControl])  // ⌃⌘Q
        case "display_off":
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/pmset")
            process.arguments = ["displaysleepnow"]
            try process.run()
        case "screensaver":
            let process = Process()
            process.executableURL = URL(fileURLWithPath: "/usr/bin/open")
            process.arguments = ["-a", "ScreenSaverEngine"]
            try process.run()
        default:
            throw Failure("Unknown system command \(command)")
        }
        return ["ok": true, "done": command]
    }

    @MainActor
    @discardableResult
    private static func runAppleScript(_ source: String) throws -> String {
        var error: NSDictionary?
        let result = NSAppleScript(source: source)?.executeAndReturnError(&error)
        if let error { throw Failure(error[NSAppleScript.errorMessage] as? String ?? "AppleScript failed") }
        return result?.stringValue ?? ""
    }
}
