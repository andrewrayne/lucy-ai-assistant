import Foundation

/// One WebSocket to the server (/ws/jarvis). Reconnects on its own.
/// Text frames are JSON events, binary frames are audio.
@MainActor
final class Connection {
    var onJSON: (([String: Any]) -> Void)?
    var onAudio: ((Data) -> Void)?
    var onStateChange: ((Bool) -> Void)?
    private(set) var isConnected = false

    private let config: Config
    private let session = URLSession(configuration: .default)
    private var task: URLSessionWebSocketTask?
    private var pingTimer: Timer?

    init(config: Config) {
        self.config = config
    }

    func start() {
        connect()
        pingTimer = Timer.scheduledTimer(withTimeInterval: 20, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.sendJSON(["type": "ping"]) }
        }
    }

    private func connect() {
        guard let url = URL(string: config.server) else {
            say("Jarvis: bad server URL in config.json")
            return
        }
        let task = session.webSocketTask(with: url)
        task.maximumMessageSize = 32 * 1024 * 1024
        self.task = task
        task.resume()
        // The first message proves this is the owner's Mac.
        sendJSON(["type": "auth", "token": config.token])
        receive(on: task)
    }

    private func receive(on task: URLSessionWebSocketTask) {
        task.receive { [weak self] result in
            Task { @MainActor in
                guard let self, self.task === task else { return }
                switch result {
                case .failure(let error):
                    say("Jarvis: connection lost (\(error.localizedDescription))")
                    self.reconnectSoon()
                case .success(.data(let data)):
                    self.onAudio?(data)
                    self.receive(on: task)
                case .success(.string(let text)):
                    if let json = try? JSONSerialization.jsonObject(with: Data(text.utf8)) as? [String: Any] {
                        if json["type"] as? String == "hello" { self.setConnected(true) }
                        self.onJSON?(json)
                    }
                    self.receive(on: task)
                case .success:
                    self.receive(on: task)
                }
            }
        }
    }

    private func reconnectSoon() {
        task?.cancel(with: .goingAway, reason: nil)
        task = nil
        setConnected(false)
        DispatchQueue.main.asyncAfter(deadline: .now() + 3) { [weak self] in
            guard let self, self.task == nil else { return }
            self.connect()
        }
    }

    private func setConnected(_ value: Bool) {
        guard value != isConnected else { return }
        isConnected = value
        onStateChange?(value)
    }

    func sendJSON(_ object: [String: Any]) {
        guard let task,
              let data = try? JSONSerialization.data(withJSONObject: object),
              let text = String(data: data, encoding: .utf8)
        else { return }
        task.send(.string(text)) { _ in }
    }

    func sendAudio(_ data: Data) {
        task?.send(.data(data)) { _ in }
    }
}
