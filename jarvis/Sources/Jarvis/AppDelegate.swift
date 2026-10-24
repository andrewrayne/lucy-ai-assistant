import AppKit
import ServiceManagement

/// The menu bar app: connects to the server, listens for "Lucy" or Shift + E,
/// streams the conversation, and runs device requests from the server.
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var statusItem: NSStatusItem!
    private let menu = NSMenu()
    private let stateItem = NSMenuItem(title: "Connecting…", action: nil, keyEquivalent: "")
    private let captionItem = NSMenuItem(title: "", action: nil, keyEquivalent: "")
    private var talkItem: NSMenuItem!
    private var wakeItem: NSMenuItem!

    private var connection: Connection?
    private let audio = Audio()
    private let wakeWord = WakeWord()
    private var hotkey: Hotkey?

    private var inConversation = false
    private var toolRunning = false
    private var lastActivity = Date()
    private var idleTimer: Timer?
    private var lastCaption = ""
    private var audioFailed = false
    /// After the owner cuts Lucy off, nothing more of her current turn is played (until "turn_complete").
    private var dropAudioUntilNextTurn = false

    private var wakeStatus = "starting"

    /// End a conversation after this long with nobody talking (`defaults write com.andrewrayne.jarvis idleSeconds 20`).
    private var idleSeconds: TimeInterval {
        let value = UserDefaults.standard.double(forKey: "idleSeconds")
        return value >= 5 ? min(value, 60) : 15
    }
    /// After the wake word, this much audio from before it is sent first ("Lucy, open Notion" in one breath).
    private let wakePreroll: Double = 2.5

    private var wakeWordEnabled: Bool {
        get { UserDefaults.standard.object(forKey: "wakeWord") as? Bool ?? true }
        set { UserDefaults.standard.set(newValue, forKey: "wakeWord") }
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.squareLength)
        buildMenu()
        updateIcon()

        guard let config = Config.load() else {
            stateItem.title = "Missing config.json — see README"
            say("Jarvis: no config at \(Config.file.path)")
            return
        }

        Permissions.requestMissing { [weak self] in self?.startAudio() }
        registerLoginItem()

        let connection = Connection(config: config)
        connection.onStateChange = { [weak self] _ in self?.updateIcon() }
        connection.onJSON = { [weak self] json in self?.handle(json) }
        connection.onAudio = { [weak self] data in
            guard let self, !self.dropAudioUntilNextTurn else { return }
            self.audio.play(data)
            self.lastActivity = Date()
        }
        connection.start()
        self.connection = connection

        hotkey = Hotkey { [weak self] in self?.toggleConversation() }
        idleTimer = Timer.scheduledTimer(withTimeInterval: 5, repeats: true) { [weak self] _ in
            Task { @MainActor in self?.checkIdle() }
        }
    }

    // MARK: Audio and wake word

    /// Start Jarvis automatically at login.
    private func registerLoginItem() {
        let service = SMAppService.mainApp
        guard service.status != .enabled else { return }
        do {
            try service.register()
            say("Jarvis: will start at login")
        } catch {
            say("Jarvis: couldn't add to login items: \(error.localizedDescription)")
        }
    }

    private func startAudio() {
        audio.onSpeechBuffer = { [weak self] buffer in self?.wakeWord.append(buffer) }
        audio.onVoiceActivity = { [weak self] in
            Task { @MainActor in self?.lastActivity = Date() }
        }
        audio.onBargeIn = { [weak self] in
            Task { @MainActor in self?.ownerTalkedOverLucy() }
        }
        audio.onPCM = { [weak self] data in
            Task { @MainActor in self?.connection?.sendAudio(data) }
        }
        do {
            try audio.start()
        } catch {
            audioFailed = true
            updateIcon()
            say("Jarvis: audio failed (\(error.localizedDescription))")
            return
        }
        wakeWord.onWake = { [weak self] in self?.startConversation(fromWakeWord: true) }
        wakeWord.onStatus = { [weak self] status in
            self?.wakeStatus = status
            self?.updateIcon()
        }
        listenForWakeWord()
    }

    private func listenForWakeWord() {
        if wakeWordEnabled && !inConversation { wakeWord.start() } else { wakeWord.stop() }
    }

    // MARK: Conversation

    /// The owner started talking while Lucy was speaking: stop her now, drop the rest of her answer and send
    /// the start of what the owner said (it was held back while she spoke).
    private func ownerTalkedOverLucy() {
        guard inConversation else { return }
        dropAudioUntilNextTurn = true
        audio.stopPlayback()
        connection?.sendAudio(audio.recent(seconds: 0.4))
        lastActivity = Date()
    }

    /// The hotkey: start a conversation; while Lucy is talking, cut her off so you can speak;
    /// otherwise end the conversation.
    @objc private func toggleConversation() {
        if !inConversation {
            startConversation()
        } else if audio.isSpeaking {
            say("Jarvis: owner cut Lucy off")
            dropAudioUntilNextTurn = true
            audio.stopPlayback()
            lastActivity = Date()
        } else {
            endConversation()
        }
    }

    private func startConversation(fromWakeWord: Bool = false) {
        guard let connection, connection.isConnected, !inConversation else {
            say("Jarvis: can't start (connected: \(connection?.isConnected == true), in conversation: \(inConversation))")
            if connection?.isConnected != true { NSSound(named: "Basso")?.play() }
            return
        }
        say("Jarvis: conversation started")
        wakeWord.stop()
        inConversation = true
        toolRunning = false
        dropAudioUntilNextTurn = false
        lastActivity = Date()
        NSSound(named: "Tink")?.play()
        connection.sendJSON([
            "type": "call_start",
            "front_app": NSWorkspace.shared.frontmostApplication?.localizedName ?? "",
            "apps": Self.installedApps,
        ])
        if fromWakeWord {
            // Words said together with the name ("Lucy, what's the weather") go first.
            connection.sendAudio(audio.recent(seconds: wakePreroll))
        }
        audio.streaming = true
        updateIcon()
    }

    private func endConversation() {
        guard inConversation else { return }
        connection?.sendJSON(["type": "call_end"])
        finishConversation()
    }

    /// The conversation is over (we ended it, or the server did).
    private func finishConversation() {
        guard inConversation else { return }
        say("Jarvis: conversation ended")
        inConversation = false
        audio.streaming = false
        audio.stopPlayback()
        NSSound(named: "Pop")?.play()
        updateIcon()
        listenForWakeWord()
    }

    private func checkIdle() {
        guard inConversation, !toolRunning else { return }
        let quietSince = max(lastActivity, audio.playingUntil)
        if Date().timeIntervalSince(quietSince) > idleSeconds { endConversation() }
    }

    // MARK: Server events

    private func handle(_ json: [String: Any]) {
        switch json["type"] as? String {
        case "hello":
            updateIcon()
        case "transcript":
            lastActivity = Date()
            if let role = json["role"] as? String, let text = json["text"] as? String {
                showCaption(role == "user" ? "You: " : "Lucy: ", text)
            }
        case "status":
            lastActivity = Date()
            toolRunning = !((json["text"] as? String) ?? "").isEmpty
        case "turn_complete":
            dropAudioUntilNextTurn = false
            lastActivity = Date()
        case "interrupted":
            // Keep dropping after a cut-off: Gemini sometimes adds a stray tail before the turn really ends.
            audio.stopPlayback()
            lastActivity = Date()
        case "ended", "call_ended":
            finishConversation()
        case "device":
            lastActivity = Date()
            Task {
                var answer = await Device.handle(json)
                answer["type"] = "device_result"
                answer["id"] = json["id"]
                self.connection?.sendJSON(answer)
                self.lastActivity = Date()
            }
        default:
            break
        }
    }

    private func showCaption(_ prefix: String, _ text: String) {
        lastCaption = lastCaption.hasPrefix(prefix) ? lastCaption + text : prefix + text.trimmingCharacters(in: .whitespaces)
        captionItem.title = String(lastCaption.suffix(80))
        captionItem.isHidden = false
    }

    // MARK: Menu

    private func buildMenu() {
        stateItem.isEnabled = false
        captionItem.isEnabled = false
        captionItem.isHidden = true
        talkItem = NSMenuItem(title: "Talk to Lucy  \(Hotkey.label)", action: #selector(toggleConversation), keyEquivalent: "")
        wakeItem = NSMenuItem(title: "Listen for “\(WakeWord.wakeWord)”", action: #selector(toggleWakeWord), keyEquivalent: "")
        let permissions = NSMenuItem(title: "Permissions…", action: #selector(showPermissions), keyEquivalent: "")
        let quit = NSMenuItem(title: "Quit Lucy", action: #selector(NSApplication.terminate(_:)), keyEquivalent: "q")
        for item in [talkItem!, wakeItem!, permissions] { item.target = self }
        [stateItem, captionItem, .separator(), talkItem, wakeItem, .separator(), permissions, quit].forEach(menu.addItem)
        statusItem.menu = menu
    }

    private func updateIcon() {
        let online = connection?.isConnected == true
        let symbol = !online ? "waveform.slash" : inConversation ? "waveform.circle.fill" : "waveform"
        statusItem.button?.image = NSImage(systemSymbolName: symbol, accessibilityDescription: "Lucy")
        stateItem.title = !online ? "Lucy: offline, reconnecting…"
            : audioFailed ? "Microphone unavailable (see Permissions…)"
            : inConversation ? "Lucy is listening" : "Lucy: connected"
        talkItem?.title = inConversation ? "End conversation  \(Hotkey.label)" : "Talk to Lucy  \(Hotkey.label)"
        wakeItem?.state = wakeWordEnabled ? .on : .off
        wakeItem?.title = wakeStatus == "listening" || !wakeWordEnabled
            ? "Listen for “\(WakeWord.wakeWord)”"
            : "Listen for “\(WakeWord.wakeWord)” (\(wakeStatus))"
    }

    @objc private func toggleWakeWord() {
        wakeWordEnabled.toggle()
        listenForWakeWord()
        updateIcon()
    }

    @objc private func showPermissions() {
        Permissions.requestMissing { [weak self] in
            let alert = NSAlert()
            alert.messageText = "Lucy permissions"
            alert.informativeText = Permissions.summary
                + "\n\nMissing ones are in System Settings → Privacy & Security. After turning one on, quit and reopen Lucy."
            alert.addButton(withTitle: "OK")
            alert.addButton(withTitle: "Open Privacy Settings")
            NSApp.activate(ignoringOtherApps: true)
            if alert.runModal() == .alertSecondButtonReturn {
                Permissions.openSettings(Permissions.accessibility ? "Privacy_ScreenCapture" : "Privacy_Accessibility")
            }
            self?.listenForWakeWord()
        }
    }

    /// App names on this Mac, so Lucy opens apps by their real names.
    static let installedApps: [String] = {
        let folders = ["/Applications", "/System/Applications", "/System/Applications/Utilities",
                       NSHomeDirectory() + "/Applications"]
        let names = folders.flatMap { folder in
            ((try? FileManager.default.contentsOfDirectory(atPath: folder)) ?? [])
                .filter { $0.hasSuffix(".app") }
                .map { String($0.dropLast(4)) }
        }
        return Array(Set(names)).sorted()
    }()
}
