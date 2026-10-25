import Foundation

/// Hands a browser task to Claude Code on this Mac: `claude -p <task> --chrome`, which drives the owner's Chrome
/// through the Claude in Chrome extension and runs on the owner's own Claude subscription (no API key involved).
/// Only the Chrome tools are allowed: no shell, no file edits. Needs Claude Code installed and logged in
/// (`claude auth login`) and the Claude in Chrome extension connected.
enum ClaudeTask {
    /// Where Claude Code usually lives. `"claude": "/path/to/claude"` in config.json overrides it.
    static func binary() -> String? {
        let fm = FileManager.default
        let home = fm.homeDirectoryForCurrentUser.path
        if let custom = Config.claudePath, fm.isExecutableFile(atPath: custom) { return custom }
        var candidates = ["\(home)/.local/bin/claude", "\(home)/.claude/local/claude"]
        // npm installs under nvm: the newest Node version first.
        let nvm = "\(home)/.nvm/versions/node"
        let versions = ((try? fm.contentsOfDirectory(atPath: nvm)) ?? [])
            .sorted { $0.compare($1, options: .numeric) == .orderedDescending }
        candidates += versions.map { "\(nvm)/\($0)/bin/claude" }
        candidates += ["/opt/homebrew/bin/claude", "/usr/local/bin/claude"]
        return candidates.first { fm.isExecutableFile(atPath: $0) }
    }

    static func run(_ prompt: String, timeout: TimeInterval, model: String?) async -> [String: Any] {
        guard let claude = binary() else {
            return ["ok": false, "error": "Claude Code isn't installed on this Mac."]
        }
        let work = Config.folder.appendingPathComponent("claude-work", isDirectory: true)
        try? FileManager.default.createDirectory(at: work, withIntermediateDirectories: true)

        let process = Process()
        process.executableURL = URL(fileURLWithPath: claude)
        var args = ["-p", prompt, "--chrome", "--allowedTools", "mcp__claude-in-chrome__*",
                    "--output-format", "json", "--max-turns", "80"]
        if let model, !model.isEmpty { args += ["--model", model] }
        process.arguments = args
        process.currentDirectoryURL = work
        // A clean environment: the owner's login (in the Keychain) is used, nothing inherited from this app.
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let binDir = (claude as NSString).deletingLastPathComponent
        process.environment = [
            "HOME": home, "USER": NSUserName(), "LANG": "en_US.UTF-8",
            "PATH": "\(binDir):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        ]
        let output = Pipe()
        process.standardOutput = output
        process.standardError = output
        process.standardInput = FileHandle.nullDevice

        say("Jarvis: Claude task started (\(claude))")
        let started = Date()
        do { try process.run() } catch {
            return ["ok": false, "error": "Couldn't start Claude Code: \(error.localizedDescription)"]
        }
        let timer = DispatchWorkItem { if process.isRunning { process.terminate() } }
        DispatchQueue.global().asyncAfter(deadline: .now() + timeout, execute: timer)
        let data: Data = await withCheckedContinuation { done in
            DispatchQueue.global().async {
                let data = output.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                done.resume(returning: data)
            }
        }
        timer.cancel()
        let seconds = Int(Date().timeIntervalSince(started))
        say("Jarvis: Claude task finished in \(seconds) s, exit \(process.terminationStatus)")

        if process.terminationReason == .uncaughtSignal {
            return ["ok": false, "error": "Claude didn't finish in \(Int(timeout / 60)) minutes and was stopped."]
        }
        let text = String(decoding: data, as: UTF8.self)
        guard let json = (try? JSONSerialization.jsonObject(with: Data(text.utf8))) as? [String: Any] else {
            return ["ok": false, "error": "Claude Code failed: \(text.suffix(600))"]
        }
        let result = json["result"] as? String ?? ""
        if json["is_error"] as? Bool == true {
            let hint = result.contains("401") || result.contains("authenticate")
                ? " Log in again on the Mac: run `claude auth login` in Terminal." : ""
            return ["ok": false, "error": "Claude: \(result.prefix(600))\(hint)"]
        }
        return ["ok": true, "result": result, "turns": json["num_turns"] ?? 0, "seconds": seconds]
    }
}
