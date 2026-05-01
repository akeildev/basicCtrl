import Cocoa
import os.log

/// Per Phase 4 D-11..D-13:
/// CGEvent tap (.listenOnly) on background DispatchQueue.
/// Streams keystroke, mouse click, and scroll events as JSONL over stdout.
/// Auto re-enables on tapDisabledByTimeout.
class LearningRecorder {
    private let logger = os.log.OSLog(subsystem: "cua.LearningRecorder", category: "recorder")
    private var eventTap: CGEventTap?
    private let queue = DispatchQueue(label: "com.cua.learning-recorder", qos: .background)
    private var runLoop: CFRunLoop?
    private var isRunning = false

    func startRecording() {
        queue.async { [weak self] in
            guard let self = self else { return }

            self.isRunning = true
            self.runLoop = CFRunLoopGetCurrent()

            // Create CGEventTap (.listenOnly) with callback
            let eventMask = CGEventMask(
                (1 << CGEventType.keyDown.rawValue) |
                (1 << CGEventType.keyUp.rawValue) |
                (1 << CGEventType.leftMouseDown.rawValue) |
                (1 << CGEventType.leftMouseUp.rawValue) |
                (1 << CGEventType.rightMouseDown.rawValue) |
                (1 << CGEventType.rightMouseUp.rawValue) |
                (1 << CGEventType.mouseMoved.rawValue) |
                (1 << CGEventType.scrollWheel.rawValue)
            )

            let tap = CGEvent.tapCreate(
                tap: .cghidEventTap,
                place: .headInsertEventTap,
                options: .listenOnly,
                eventsOfInterest: eventMask,
                callback: Self.eventCallback,
                userInfo: UnsafeMutableRawPointer(Unmanaged.passUnretained(self).toOpaque())
            )

            guard let tap = tap else {
                os_log("Failed to create CGEventTap", log: self.logger, type: .error)
                return
            }

            // Register with CFRunLoop on the bg queue
            let runLoop = CFRunLoopGetCurrent()
            CGEventTapEnable(tap, true)
            CFRunLoopAddSource(runLoop, tap, .commonModes)
            self.eventTap = tap

            os_log("CGEventTap started on background queue", log: self.logger, type: .info)

            // Run loop
            CFRunLoopRun()
        }
    }

    func stopRecording() {
        queue.async { [weak self] in
            guard let self = self else { return }

            self.isRunning = false

            if let tap = self.eventTap {
                CGEventTapEnable(tap, false)
            }

            if let runLoop = self.runLoop {
                CFRunLoopStop(runLoop)
            }

            os_log("CGEventTap stopped", log: self.logger, type: .info)
        }
    }

    /// EventTap callback — receives CGEvent, converts to JSONL.
    /// Static callback required by CGEventTapCreate; unwraps self via userInfo.
    private static let eventCallback: CGEventTapCallBack = { proxy, type, event, userInfo in
        guard let userInfo = userInfo else { return event }

        let selfPtr = Unmanaged<LearningRecorder>.fromOpaque(userInfo)
        let `self` = selfPtr.takeUnretainedValue()

        // Handle tapDisabledByTimeout — re-enable the tap
        if type == .tapDisabledByTimeout {
            CGEventTapEnable(proxy, true)
            self.emitEvent(
                type: "tap_re_enabled",
                payload: ["ts": Date().timeIntervalSince1970]
            )
            return event
        }

        // Process keystroke events
        if type == .keyDown || type == .keyUp {
            if let keyCode = event.getIntegerValueField(.keyboardEventKeycode) as? Int {
                let keyStr = Self.keyCodeToString(Int32(keyCode))
                let eventType = type == .keyDown ? "key_down" : "key_up"
                self.emitEvent(
                    type: eventType,
                    payload: [
                        "key": keyStr,
                        "key_code": keyCode,
                        "ts": Date().timeIntervalSince1970
                    ]
                )
            }
        }

        // Process mouse click events
        if type == .leftMouseDown || type == .leftMouseUp ||
           type == .rightMouseDown || type == .rightMouseUp {
            let location = event.location
            let eventType: String
            switch type {
            case .leftMouseDown: eventType = "left_mouse_down"
            case .leftMouseUp: eventType = "left_mouse_up"
            case .rightMouseDown: eventType = "right_mouse_down"
            case .rightMouseUp: eventType = "right_mouse_up"
            default: eventType = "mouse_event"
            }

            self.emitEvent(
                type: eventType,
                payload: [
                    "x": location.x,
                    "y": location.y,
                    "ts": Date().timeIntervalSince1970
                ]
            )
        }

        // Process scroll events
        if type == .scrollWheel {
            let deltaY = event.getIntegerValueField(.scrollWheelEventDeltaAxis1) as? Int ?? 0
            let deltaX = event.getIntegerValueField(.scrollWheelEventDeltaAxis2) as? Int ?? 0

            self.emitEvent(
                type: "scroll",
                payload: [
                    "dx": deltaX,
                    "dy": deltaY,
                    "ts": Date().timeIntervalSince1970
                ]
            )
        }

        // Process mouse move events
        if type == .mouseMoved {
            let location = event.location
            self.emitEvent(
                type: "mouse_moved",
                payload: [
                    "x": location.x,
                    "y": location.y,
                    "ts": Date().timeIntervalSince1970
                ]
            )
        }

        return event
    }

    /// Emit a JSONL event to stdout.
    /// Per Phase 1 IPC pattern: one JSON object per line, newline-terminated.
    private func emitEvent(type: String, payload: [String: Any]) {
        let event: [String: Any] = [
            "type": type,
            "ts": payload["ts"] ?? Date().timeIntervalSince1970,
            "payload": payload
        ]

        if let json = try? JSONSerialization.data(withJSONObject: event, options: []),
           let jsonStr = String(data: json, encoding: .utf8) {
            print(jsonStr)
            fflush(stdout)
        }
    }

    /// Convert macOS key code to string representation.
    /// Reference: /Library/Frameworks/Carbon.framework/Versions/A/Frameworks/HIToolbox.framework/Headers/Events.h
    private static func keyCodeToString(_ keyCode: Int32) -> String {
        // Common printable keys
        switch keyCode {
        case 0: return "a"
        case 1: return "s"
        case 2: return "d"
        case 3: return "f"
        case 4: return "h"
        case 5: return "g"
        case 6: return "z"
        case 7: return "x"
        case 8: return "c"
        case 9: return "v"
        case 11: return "b"
        case 12: return "q"
        case 13: return "w"
        case 14: return "e"
        case 15: return "r"
        case 16: return "y"
        case 17: return "t"
        case 18: return "1"
        case 19: return "2"
        case 20: return "3"
        case 21: return "4"
        case 22: return "6"
        case 23: return "5"
        case 24: return "="
        case 25: return "9"
        case 26: return "7"
        case 27: return "-"
        case 28: return "8"
        case 29: return "0"
        case 30: return "]"
        case 31: return "o"
        case 32: return "u"
        case 33: return "["
        case 34: return "i"
        case 35: return "p"
        case 36: return "\n"  // Return
        case 37: return "l"
        case 38: return "j"
        case 39: return "'"
        case 40: return "k"
        case 41: return ";"
        case 42: return "\\"
        case 43: return ","
        case 44: return "/"
        case 45: return "n"
        case 46: return "m"
        case 47: return "."
        case 48: return "\t"  // Tab
        case 49: return " "
        case 50: return "`"
        case 51: return "\u{0008}"  // Backspace
        case 53: return "\u{001B}"  // Escape
        default:
            return "key_\(keyCode)"
        }
    }
}

// MARK: - Main entry point for testing

#if DEBUG
@main
struct LearningRecorderApp {
    static func main() {
        let recorder = LearningRecorder()
        recorder.startRecording()

        // Keep the app running
        RunLoop.main.run()
    }
}
#endif
