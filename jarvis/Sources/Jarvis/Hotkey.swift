import Carbon

/// Global hotkey ⇧E (Shift + E): start or end a conversation from any app.
/// Carbon's RegisterEventHotKey needs no permission. Note: while Jarvis runs, Shift + E is taken by
/// Jarvis, so a capital E can't be typed with it (Caps Lock + E still works).
final class Hotkey {
    static let label = "⇧E"
    private static var action: (() -> Void)?
    private static var lastFired = Date.distantPast
    private var ref: EventHotKeyRef?

    init(action: @escaping () -> Void) {
        Hotkey.action = action
        var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
        let installed = InstallEventHandler(GetEventDispatcherTarget(), { _, _, _ in
            DispatchQueue.main.async {
                guard Date().timeIntervalSince(Hotkey.lastFired) > 0.5 else { return }
                Hotkey.lastFired = Date()
                say("Jarvis: hotkey pressed")
                Hotkey.action?()
            }
            return noErr
        }, 1, &spec, nil, nil)
        let id = EventHotKeyID(signature: OSType(0x4A52_5653), id: 1)  // "JRVS"
        let registered = RegisterEventHotKey(UInt32(kVK_ANSI_E), UInt32(shiftKey), id, GetEventDispatcherTarget(), 0, &ref)
        say("Jarvis: hotkey ⇧E handler \(installed), register \(registered)")
    }
}
