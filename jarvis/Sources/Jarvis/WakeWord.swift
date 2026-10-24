import AVFoundation
import Speech

/// Listens for the wake word "Lucy" with Apple's on-device SpeechAnalyzer (macOS 26+).
///
/// - Runs entirely on the Mac: nothing is sent anywhere before the name is heard, and it costs nothing.
/// - Doesn't need macOS Dictation to be on (the older SFSpeechRecognizer did, and refused to run).
/// - Two independent recognisers, each with its own analyzer (in one analyzer the second never produced results):
///   English (SpeechTranscriber) and a far-field Russian dictation model, so the name is caught whether it's
///   said in an English or a Russian sentence. The English model never writes the Cyrillic spelling.
/// - A speech detector skips silence; partial (volatile) results catch the name quickly.
/// - The speech models are downloaded from Apple once, the first time.
final class WakeWord {
    static let wakeWord = "Lucy"

    var onWake: (() -> Void)?
    /// Short status for the menu ("listening", "downloading speech model…", an error).
    var onStatus: ((String) -> Void)?
    private(set) var isListening = false

    /// Spellings the recognisers produce for the name.
    static let variants: Set<String> = [
        "lucy", "lucie", "lucey", "luci", "lusi", "lusy", "loosey", "lucy's", "luce",
        "люси", "люсі", "люся", "люсь", "люсе", "люсю",
    ]

    /// Troubleshooting only: `defaults write com.andrewrayne.jarvis debugWakeWord -bool YES` logs what the
    /// recognisers hear (off by default: it would log everything said near the Mac).
    static let debug = UserDefaults.standard.bool(forKey: "debugWakeWord")

    private var listeners: [Listener] = []
    private let lock = NSLock()
    private var generation = 0

    /// Start (or restart) listening. Call on the main thread.
    func start() {
        stop()
        isListening = true
        generation += 1
        let current = generation
        let english = Listener(.english)
        let russian = Listener(.russian)
        let all = [english, russian]
        lock.withLock { listeners = all }
        for listener in all {
            listener.onText = { [weak self] text in self?.check(text, current) }
            Task {
                do {
                    try await listener.start()
                    self.status("listening")
                } catch {
                    say("Jarvis: \(listener.name) wake word recogniser failed: \(error.localizedDescription)")
                    self.status("unavailable: \(error.localizedDescription)")
                    DispatchQueue.main.asyncAfter(deadline: .now() + 30) { [weak self] in
                        guard let self, self.isListening, current == self.generation else { return }
                        self.start()  // e.g. the model download was interrupted
                    }
                }
            }
        }
    }

    func stop() {
        isListening = false
        generation += 1
        let old = lock.withLock { () -> [Listener] in
            defer { listeners = [] }
            return listeners
        }
        old.forEach { $0.stop() }
    }

    /// Microphone audio (16 kHz mono float), any thread.
    func append(_ buffer: AVAudioPCMBuffer) {
        let current = lock.withLock { listeners }
        current.forEach { $0.append(buffer) }
    }

    private func check(_ text: String, _ current: Int) {
        if WakeWord.debug { say("Jarvis: heard “\(text)”") }
        let words = text.lowercased().components(separatedBy: CharacterSet.letters.inverted.subtracting(["'"]))
        guard words.contains(where: { WakeWord.variants.contains($0) }) else { return }
        DispatchQueue.main.async { [weak self] in
            guard let self, self.isListening, current == self.generation else { return }
            say("Jarvis: wake word heard")
            self.stop()
            self.onWake?()
        }
    }

    private func status(_ text: String) {
        DispatchQueue.main.async { [weak self] in self?.onStatus?(text) }
    }
}

/// One on-device recogniser with its own SpeechAnalyzer and audio stream.
private final class Listener {
    enum Language { case english, russian }

    let language: Language
    var name: String { language == .english ? "English" : "Russian" }
    var onText: ((String) -> Void)?

    private let lock = NSLock()
    private var continuation: AsyncStream<AnalyzerInput>.Continuation?
    private var converter: AVAudioConverter?
    private var format: AVAudioFormat?
    private var analyzer: SpeechAnalyzer?
    private var resultsTask: Task<Void, Never>?

    init(_ language: Language) {
        self.language = language
    }

    func start() async throws {
        let transcriber: any SpeechModule
        switch language {
        case .english:
            let module = SpeechTranscriber(locale: Locale(identifier: "en-US"), transcriptionOptions: [],
                                           reportingOptions: [.volatileResults, .fastResults], attributeOptions: [])
            transcriber = module
            resultsTask = Task { [weak self] in
                do {
                    for try await result in module.results { self?.onText?(String(result.text.characters)) }
                } catch { say("Jarvis: English recogniser stopped: \(error.localizedDescription)") }
            }
        case .russian:
            guard let locale = await DictationTranscriber.supportedLocale(equivalentTo: Locale(identifier: "ru-RU")) else {
                say("Jarvis: Russian dictation model not available on this Mac")
                return
            }
            let module = DictationTranscriber(locale: locale, contentHints: [.farField, .shortForm], transcriptionOptions: [],
                                              reportingOptions: [.volatileResults, .frequentFinalization], attributeOptions: [])
            transcriber = module
            resultsTask = Task { [weak self] in
                do {
                    for try await result in module.results { self?.onText?(String(result.text.characters)) }
                } catch { say("Jarvis: Russian recogniser stopped: \(error.localizedDescription)") }
            }
        }

        if let request = try await AssetInventory.assetInstallationRequest(supporting: [transcriber]) {
            say("Jarvis: downloading the \(name) speech model")
            try await request.downloadAndInstall()
        }

        // A speech detector in front skips silence; if it can't be used, run without it.
        let analyzer = SpeechAnalyzer(modules: [SpeechDetector(detectionOptions: .init(sensitivityLevel: .medium), reportResults: false), transcriber])
        var best = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: analyzer.modules)
        do {
            try await analyzer.prepareToAnalyze(in: best)
        } catch {
            say("Jarvis: speech detector unavailable for \(name) (\(error.localizedDescription))")
            try await analyzer.setModules([transcriber])
            best = await SpeechAnalyzer.bestAvailableAudioFormat(compatibleWith: [transcriber])
            try await analyzer.prepareToAnalyze(in: best)
        }

        let (stream, continuation) = AsyncStream<AnalyzerInput>.makeStream(bufferingPolicy: .bufferingNewest(100))
        let input = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Audio.sampleRate, channels: 1, interleaved: false)!
        lock.withLock {
            self.continuation = continuation
            self.analyzer = analyzer
            self.format = best ?? input
            self.converter = (best == nil || best == input) ? nil : AVAudioConverter(from: input, to: best!)
        }
        try await analyzer.start(inputSequence: stream)
        say("Jarvis: listening for “\(WakeWord.wakeWord)” (\(name), on-device)")
    }

    func stop() {
        resultsTask?.cancel()
        let (cont, analyzer) = lock.withLock { () -> (AsyncStream<AnalyzerInput>.Continuation?, SpeechAnalyzer?) in
            defer { continuation = nil; converter = nil; self.analyzer = nil }
            return (continuation, self.analyzer)
        }
        cont?.finish()
        if let analyzer { Task { await analyzer.cancelAndFinishNow() } }
    }

    /// 16 kHz mono float audio, any thread.
    func append(_ buffer: AVAudioPCMBuffer) {
        let (cont, converter, format) = lock.withLock { (continuation, self.converter, self.format) }
        guard let cont, let format else { return }
        guard let converter else {
            cont.yield(AnalyzerInput(buffer: buffer))
            return
        }
        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * format.sampleRate / buffer.format.sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: format, frameCapacity: capacity) else { return }
        var consumed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if consumed {
                status.pointee = .noDataNow
                return nil
            }
            consumed = true
            status.pointee = .haveData
            return buffer
        }
        if error == nil, out.frameLength > 0 { cont.yield(AnalyzerInput(buffer: out)) }
    }
}
