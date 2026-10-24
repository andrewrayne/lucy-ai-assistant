import AVFoundation
import os

let logger = Logger(subsystem: "com.andrewrayne.jarvis", category: "app")

/// Write a line to the macOS log (Console.app, or `log stream --predicate 'subsystem == "com.andrewrayne.jarvis"'`).
func say(_ message: String) {
    logger.notice("\(message, privacy: .public)")
}

/// The audio hub: the only place that opens the microphone, and the player for Lucy's voice.
///
/// Microphone → first channel only → 16 kHz mono → low-cut filter + automatic level → listeners:
/// - the wake word gets every buffer while idle,
/// - the server gets 16-bit PCM while a conversation is on,
/// - the last 8 seconds stay in a ring buffer, so words said together with the wake word ("Lucy, open Notion")
///   can be sent first.
///
/// No echo cancellation (Apple's voice processing gave pure silence on the Studio Display). Instead the mic is
/// paused while Lucy's voice plays, so she never hears herself. Her voice plays on its own audio engine.
final class Audio {
    /// 16 kHz mono float buffers (audio thread), for the wake word.
    var onSpeechBuffer: ((AVAudioPCMBuffer) -> Void)?
    /// 16 kHz 16-bit PCM (audio thread), for the server while `streaming` is on.
    var onPCM: ((Data) -> Void)?
    /// Called (audio thread) when the owner's voice is louder than about -42 dB.
    var onVoiceActivity: (() -> Void)?
    /// Called (audio thread) once when the owner starts talking over Lucy.
    var onBargeIn: (() -> Void)?

    static let sampleRate = 16_000.0
    private let micFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: Audio.sampleRate, channels: 1, interleaved: false)!
    private let playFormat = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: 24_000, channels: 1, interleaved: false)!

    private var inputEngine = AVAudioEngine()
    private let outputEngine = AVAudioEngine()
    private let player = AVAudioPlayerNode()
    private var converter: AVAudioConverter?
    private var firstChannelFormat: AVAudioFormat?

    private let lock = NSLock()
    private var _streaming = false
    private var _playingUntil = Date.distantPast
    private var ring = Data()
    private let ringBytes = Int(Audio.sampleRate) * 2 * 8  // 8 seconds of 16-bit audio
    private var lowCut = LowCut(cutoff: 150, sampleRate: Audio.sampleRate)
    private var level = AutoLevel()
    // Talking over Lucy ("barge-in"). There's no echo cancellation, so we compare the mic with what Lucy is
    // playing: echo = coupling × her loudness. Clearly more than that, for about 250 ms, is the owner.
    private var playback: [(time: Date, rms: Float)] = []  // Lucy's loudness every 20 ms, on the playback clock
    /// How much of Lucy's voice reaches the mic (mic loudness / her loudness), learned while only she speaks and
    /// remembered between conversations. 0.35 was measured on the owner's Studio Display.
    private var coupling = Float(UserDefaults.standard.object(forKey: "echoCoupling") as? Double ?? 0.35)
    private var ratios: [Float] = []
    private var answerStarted = Date.distantPast
    private var lastDebug = Date.distantPast
    private let debugBargeIn = UserDefaults.standard.bool(forKey: "debugBargeIn")
    private var loudRun = 0
    private var bargedIn = false
    private let bargeInEnabled = UserDefaults.standard.object(forKey: "voiceBargeIn") as? Bool ?? true
    private let bargeInFactor = Float(UserDefaults.standard.object(forKey: "bargeInFactor") as? Double ?? 2)
    private var _peak: Float = 0
    private var _sentBytes = 0
    private var _lastReport = Date()

    var streaming: Bool {
        get { lock.withLock { _streaming } }
        set { lock.withLock { _streaming = newValue } }
    }

    /// When Lucy's queued voice finishes.
    var playingUntil: Date { lock.withLock { _playingUntil } }
    var isSpeaking: Bool { Date() < playingUntil }

    // MARK: Start

    func start() throws {
        try startOutput()
        try startInput()
    }

    private func startOutput() throws {
        outputEngine.attach(player)
        outputEngine.connect(player, to: outputEngine.mainMixerNode, format: playFormat)
        outputEngine.prepare()
        try outputEngine.start()
        player.play()
    }

    /// The input engine is created fresh on every (re)start, so one failed attempt can't break the next.
    func startInput() throws {
        inputEngine.inputNode.removeTap(onBus: 0)
        inputEngine.stop()
        inputEngine = AVAudioEngine()
        let input = inputEngine.inputNode
        let hardware = input.outputFormat(forBus: 0)
        guard hardware.sampleRate > 0, hardware.channelCount > 0 else {
            throw NSError(domain: "Jarvis", code: 1, userInfo: [NSLocalizedDescriptionKey: "No microphone found"])
        }
        // Some mics deliver several channels with the voice only in the first: take that one, don't mix.
        let mono = AVAudioFormat(commonFormat: .pcmFormatFloat32, sampleRate: hardware.sampleRate, channels: 1, interleaved: false)!
        firstChannelFormat = mono
        converter = AVAudioConverter(from: mono, to: micFormat)
        input.installTap(onBus: 0, bufferSize: 4096, format: hardware) { [weak self] buffer, _ in
            self?.process(buffer)
        }
        inputEngine.prepare()
        try inputEngine.start()
        say("Jarvis: microphone on (\(hardware.channelCount) ch @ \(Int(hardware.sampleRate)) Hz, using channel 1)")
    }

    // MARK: Microphone

    private func process(_ buffer: AVAudioPCMBuffer) {
        guard let converter, let firstChannelFormat, let source = buffer.floatChannelData,
              let mono = AVAudioPCMBuffer(pcmFormat: firstChannelFormat, frameCapacity: buffer.frameLength)
        else { return }
        mono.frameLength = buffer.frameLength
        mono.floatChannelData![0].update(from: source[0], count: Int(buffer.frameLength))

        let capacity = AVAudioFrameCount(Double(buffer.frameLength) * Audio.sampleRate / buffer.format.sampleRate) + 64
        guard let out = AVAudioPCMBuffer(pcmFormat: micFormat, frameCapacity: capacity) else { return }
        var consumed = false
        var error: NSError?
        converter.convert(to: out, error: &error) { _, status in
            if consumed {
                status.pointee = .noDataNow
                return nil
            }
            consumed = true
            status.pointee = .haveData
            return mono
        }
        guard error == nil, out.frameLength > 0, let samples = out.floatChannelData?[0] else { return }
        let count = Int(out.frameLength)

        // Loudness of the raw voice, for "is the owner talking?" (about -42 dB and up).
        var sum: Float = 0
        for i in 0..<count { sum += samples[i] * samples[i] }
        let rms = (sum / Float(count)).squareRoot()

        // Cut low rumble and bring quiet speech up to a steady level (the Studio Display mic is quiet and
        // boomy; Gemini Live's speech detection ignored it until both were fixed).
        for i in 0..<count {
            samples[i] = level.process(lowCut.process(samples[i]))
        }

        var lucySpeaking = Date() < playingUntil.addingTimeInterval(0.8)
        if lucySpeaking && bargeInEnabled && detectBargeIn(micRMS: rms) {
            lucySpeaking = false  // she's being cut off: let the owner's voice through right away
        }
        if rms > 0.008 && !lucySpeaking { onVoiceActivity?() }
        onSpeechBuffer?(out)

        var pcm = Data(count: count * 2)
        var peak: Float = 0
        pcm.withUnsafeMutableBytes { raw in
            let dst = raw.bindMemory(to: Int16.self)
            for i in 0..<count {
                peak = max(peak, abs(samples[i]))
                dst[i] = Int16(max(-1, min(1, samples[i])) * 32767).littleEndian
            }
        }

        let (send, report, maxPeak, sent): (Bool, Bool, Float, Int) = lock.withLock {
            ring.append(pcm)
            if ring.count > ringBytes { ring.removeFirst(ring.count - ringBytes) }
            _peak = max(_peak, peak)
            let send = _streaming && !lucySpeaking
            if send { _sentBytes += pcm.count }
            guard _streaming, Date().timeIntervalSince(_lastReport) > 2 else { return (send, false, 0, 0) }
            defer { _peak = 0; _sentBytes = 0; _lastReport = Date() }
            return (send, true, _peak, _sentBytes)
        }
        if report { say("Jarvis: mic level \(String(format: "%.3f", maxPeak)), sent \(sent) bytes in 2 s") }
        if send { onPCM?(pcm) }
    }

    /// Is the owner talking over Lucy? Called for every mic buffer (~85 ms) while she speaks.
    private func detectBargeIn(micRMS: Float) -> Bool {
        let now = Date()
        let (echoSource, already): (Float, Bool) = lock.withLock {
            playback.removeAll { $0.time < now.addingTimeInterval(-1) }
            // Her loudest moment over the last 600 ms (speakers, the display and the room delay the echo).
            let recent = playback.filter { $0.time >= now.addingTimeInterval(-0.6) && $0.time <= now.addingTimeInterval(0.1) }
            return (recent.map(\.rms).max() ?? 0, bargedIn)
        }
        if already { return true }
        // Only while her voice is actually audible (not in the short pause after it), and only for a clearly
        // audible voice (about -36 dB and up), so room noise never cuts her off.
        guard echoSource > 0.01 else {
            loudRun = 0
            return false
        }
        let expected = coupling * echoSource
        if debugBargeIn && now.timeIntervalSince(lastDebug) > 0.5 {
            lastDebug = now
            say(String(format: "Jarvis: barge-in check mic %.3f, Lucy %.3f, coupling %.2f", micRMS, echoSource, coupling))
        }
        // The first 0.7 s of each answer only teach us how loud her echo is.
        let learning = now.timeIntervalSince(answerStarted) < 0.7
        if !learning && micRMS > max(bargeInFactor * expected, 0.016) {
            loudRun += 1
        } else {
            loudRun = 0
            // Learn how much of Lucy's voice reaches the mic: the 90th percentile of the last ~8 s.
            if echoSource > 0.03 {
                ratios.append(min(2, micRMS / echoSource))
                if ratios.count > 100 { ratios.removeFirst(ratios.count - 100) }
                if ratios.count >= 10 {
                    let sorted = ratios.sorted()
                    coupling = max(0.05, sorted[Int(Double(sorted.count - 1) * 0.9)])
                    if ratios.count % 20 == 0 { UserDefaults.standard.set(Double(coupling), forKey: "echoCoupling") }
                }
            }
        }
        guard loudRun >= 3 else { return false }
        loudRun = 0
        lock.withLock { bargedIn = true }
        say(String(format: "Jarvis: owner talked over Lucy (mic %.3f, her echo ~%.3f)", micRMS, expected))
        onBargeIn?()
        return true
    }

    /// The last `seconds` of microphone audio (16 kHz 16-bit PCM).
    func recent(seconds: Double) -> Data {
        lock.withLock {
            let bytes = min(ring.count, Int(seconds * Audio.sampleRate) * 2)
            return Data(ring.suffix(bytes))
        }
    }

    // MARK: Lucy's voice

    /// Queue a chunk of Lucy's voice (24 kHz 16-bit mono PCM).
    func play(_ data: Data) {
        let frames = data.count / 2
        guard frames > 0,
              let buffer = AVAudioPCMBuffer(pcmFormat: playFormat, frameCapacity: AVAudioFrameCount(frames))
        else { return }
        buffer.frameLength = AVAudioFrameCount(frames)
        let dst = buffer.floatChannelData![0]
        data.withUnsafeBytes { raw in
            for i in 0..<frames {
                dst[i] = Float(Int16(littleEndian: raw.loadUnaligned(fromByteOffset: i * 2, as: Int16.self))) / 32768
            }
        }
        if !outputEngine.isRunning { try? outputEngine.start() }
        player.scheduleBuffer(buffer)
        if !player.isPlaying { player.play() }
        let seconds = Double(frames) / playFormat.sampleRate
        // Lucy's loudness every 20 ms, placed at the time it will actually play.
        let step = Int(playFormat.sampleRate * 0.02)
        lock.withLock {
            let start = max(_playingUntil, Date())
            if _playingUntil < Date() {  // a new answer starts
                bargedIn = false
                answerStarted = start
            }
            for offset in stride(from: 0, to: frames, by: step) {
                let end = min(frames, offset + step)
                var sum: Float = 0
                for i in offset..<end { sum += dst[i] * dst[i] }
                playback.append((start.addingTimeInterval(Double(offset) / playFormat.sampleRate), (sum / Float(end - offset)).squareRoot()))
            }
            _playingUntil = start.addingTimeInterval(seconds)
        }
    }

    /// Stop Lucy's voice right away (cut off, or the conversation ended).
    func stopPlayback() {
        player.stop()
        player.play()
        // Nothing is playing any more, so the mic can open right away.
        lock.withLock {
            _playingUntil = .distantPast
            playback.removeAll()
        }
    }
}

/// Second-order Butterworth high-pass filter (removes rumble below the cutoff).
struct LowCut {
    private let b0, b1, b2, a1, a2: Float
    private var x1: Float = 0, x2: Float = 0, y1: Float = 0, y2: Float = 0

    init(cutoff: Double, sampleRate: Double) {
        let w0 = 2 * Double.pi * cutoff / sampleRate
        let alpha = sin(w0) / (2 * 0.7071)
        let c = cos(w0), a0 = 1 + alpha
        b0 = Float((1 + c) / 2 / a0)
        b1 = Float(-(1 + c) / a0)
        b2 = Float((1 + c) / 2 / a0)
        a1 = Float(-2 * c / a0)
        a2 = Float((1 - alpha) / a0)
    }

    mutating func process(_ x: Float) -> Float {
        let y = b0 * x + b1 * x1 + b2 * x2 - a1 * y1 - a2 * y2
        x2 = x1; x1 = x; y2 = y1; y1 = y
        return y
    }
}

/// Automatic level: follows the loudness of the voice and raises quiet speech towards a steady level
/// (up to ×6), without boosting silence much and without clipping loud speech.
struct AutoLevel {
    private var envelope: Float = 0.05
    private let target: Float = 0.35
    private let maxGain: Float = 6

    mutating func process(_ x: Float) -> Float {
        let a = abs(x)
        // Fast attack, slow release (about a second).
        envelope = a > envelope ? envelope + (a - envelope) * 0.01 : envelope + (a - envelope) * 0.00006
        let gain = min(maxGain, max(1, target / max(envelope, 0.02)))
        return tanhf(x * gain)
    }
}
