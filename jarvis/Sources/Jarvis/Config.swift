import Foundation

/// Settings live in ~/Library/Application Support/Jarvis/config.json (never in the app or in git):
/// { "server": "wss://<your-railway-domain>/ws/jarvis", "token": "<JARVIS_TOKEN>" }
/// Optional: "claude": "/path/to/claude" if Claude Code isn't found on its own (see ClaudeTask).
struct Config: Codable {
    var server: String
    var token: String
    var claude: String?

    static var claudePath: String? { load()?.claude }

    static var folder: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/Jarvis", isDirectory: true)
    }

    static var file: URL { folder.appendingPathComponent("config.json") }

    static func load() -> Config? {
        guard let data = try? Data(contentsOf: file),
              let config = try? JSONDecoder().decode(Config.self, from: data),
              !config.server.isEmpty, !config.token.isEmpty
        else { return nil }
        return config
    }
}
