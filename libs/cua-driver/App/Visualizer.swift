import AppKit
import CoreGraphics
import Darwin
import os.log

/// Visualizer sidecar — NSPanel host for ghost cursor, element highlights, HUD.
/// Listens on /tmp/cua-visualizer.sock for NDJSON commands from Python overlay.
/// All rendering respects SCContentFilter(excludingWindows:) for verifier isolation (P9, P10).
class VisualizerApplication: NSApplication {
    static let shared = VisualizerApplication()
    private var visualizerWindow: VisualizerPanel?

    // MARK: - Overlay Window ID Registry (for ScreenRecorder P9/P10 exclusion)
    /// Global overlay window IDs — ScreenRecorder reads these via getOverlayWindowIDs()
    private static var overlayWindowIDRegistry: [CGWindowID] = []

    static func registerOverlayWindowID(_ windowID: CGWindowID) {
        overlayWindowIDRegistry.append(windowID)
    }

    static func getOverlayWindowIDs() -> [CGWindowID] {
        return overlayWindowIDRegistry
    }

    override func run() {
        // Silence app delegate warnings
        delegate = AppDelegate()

        // Create the visualizer panel
        visualizerWindow = VisualizerPanel()
        visualizerWindow?.center()
        visualizerWindow?.orderFront(nil)

        // Register this window's ID for ScreenRecorder to exclude (P9/P10 mitigation)
        if let windowID = visualizerWindow?.windowNumber as? CGWindowID {
            VisualizerApplication.registerOverlayWindowID(windowID)
        }

        // Start socket listener
        SocketListener.shared.start()

        super.run()
    }
}

class VisualizerPanel: NSPanel {
    private let contentView: VisualizerContentView
    var ghostCursorView: GhostCursorView
    var highlightView: HighlightOverlayView
    var hudView: HUDView?

    init() {
        // UI-SPEC L44-46: .popUpMenu level, borderless, ignores input
        super.init(
            contentRect: NSScreen.main?.frame ?? NSRect(x: 0, y: 0, width: 1440, height: 900),
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )

        self.level = .popUpMenu  // Above normal windows, below floating palettes
        self.isOpaque = false
        self.backgroundColor = NSColor.clear
        self.ignoresMouseEvents = true  // P11 — overlay never captures input
        self.canJoinAllSpaces = true  // Visible on all Spaces
        self.collectionBehavior = [.canJoinAllSpaces, .stationary, .ignoresCycle]
        self.hidesOnDeactivate = false

        // Content view hosts ghost cursor + highlight views
        contentView = VisualizerContentView(frame: self.frame)
        ghostCursorView = GhostCursorView(frame: self.frame)
        highlightView = HighlightOverlayView(frame: self.frame)

        contentView.addSubview(ghostCursorView)
        contentView.addSubview(highlightView)

        self.contentView = contentView
    }

    required init?(coder: NSCoder) {
        fatalError("init(coder:) not implemented")
    }

    func updateHUDActions(_ actions: [HUDActionEntry], sessionStart: String, goal: String) {
        if let hudView = hudView {
            hudView.updateActions(actions)
            hudView.setSessionMetadata(sessionStart: sessionStart, goal: goal)
        }
    }
}

class VisualizerContentView: NSView {
    override func isOpaque() -> Bool { false }
}

class AppDelegate: NSObject, NSApplicationDelegate {
    func applicationShouldTerminateAfterLastWindowClosed(_: NSApplication) -> Bool {
        return true
    }
}

// MARK: - Socket Listener (DispatchSourceRead pattern from LearningRecorder)

class SocketListener {
    static let shared = SocketListener()
    private let socketPath = "/tmp/cua-visualizer.sock"
    private let logger = os.log.OSLog(subsystem: "cua.visualizer", category: "socket")
    private var socketFd: Int32 = -1
    private var source: DispatchSourceRead?

    func start() {
        let queue = DispatchQueue(label: "com.cua.visualizer-socket", qos: .userInteractive)
        queue.async { [weak self] in
            self?.listenForCommands()
        }
    }

    private func listenForCommands() {
        // Remove old socket file
        try? FileManager.default.removeItem(atPath: socketPath)

        // Create unix domain socket
        var addr = sockaddr_un()
        addr.sun_family = sa_family_t(AF_UNIX)
        withUnsafeMutableBytes(of: &addr.sun_path) { bytes in
            memcpy(bytes.baseAddress, socketPath, socketPath.utf8.count)
        }

        socketFd = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard socketFd >= 0 else {
            os_log("Failed to create socket", log: self.logger, type: .error)
            return
        }

        // Bind and listen
        let result = withUnsafePointer(to: &addr) {
            Darwin.bind(socketFd, UnsafeRawPointer($0).assumingMemoryBound(to: sockaddr.self), socklen_t(MemoryLayout<sockaddr_un>.size))
        }

        guard result == 0 else {
            os_log("Failed to bind socket", log: self.logger, type: .error)
            return
        }

        Darwin.listen(socketFd, 1)

        // Set up DispatchSourceRead to accept connections
        let source = DispatchSource.makeReadSource(fileDescriptor: socketFd)
        self.source = source

        source.setEventHandler { [weak self] in
            self?.acceptConnection()
        }
        source.resume()

        os_log("Visualizer socket listener started on %{public}s", log: self.logger, type: .info, self.socketPath)
    }

    private func acceptConnection() {
        var addr = sockaddr_un()
        var addrLen = socklen_t(MemoryLayout<sockaddr_un>.size)

        let clientFd = Darwin.accept(socketFd, &addr, &addrLen)
        guard clientFd >= 0 else { return }

        // Read NDJSON from client
        let fileHandle = FileHandle(fileDescriptor: clientFd, closeOnDealloc: true)
        let data = fileHandle.readDataToEndOfFile()

        guard let jsonLine = String(data: data, encoding: .utf8) else { return }

        // Parse NDJSON lines (one or more)
        for line in jsonLine.split(separator: "\n", omittingEmptySubsequences: true) {
            if let jsonData = line.data(using: .utf8),
               let dict = try? JSONSerialization.jsonObject(with: jsonData) as? [String: Any],
               let cmd = dict["cmd"] as? String {
                handleCommand(dict, cmdType: cmd)
            }
        }
    }

    private func handleCommand(_ dict: [String: Any], cmdType: String) {
        DispatchQueue.main.async {
            guard let appDelegate = NSApplication.shared.delegate as? AppDelegate else { return }
            guard let window = NSApplication.shared.windows.first(where: { $0 is VisualizerPanel }) as? VisualizerPanel else {
                return
            }

            switch cmdType {
            case "ghost_cursor":
                if let x = dict["x"] as? Double, let y = dict["y"] as? Double,
                   let durationMs = dict["duration_ms"] as? Int {
                    window.ghostCursorView.animateToTarget(x: x, y: y, duration: durationMs)
                }
            case "highlight":
                if let bboxX = dict["bbox_x"] as? Double,
                   let bboxY = dict["bbox_y"] as? Double,
                   let bboxWidth = dict["bbox_width"] as? Double,
                   let bboxHeight = dict["bbox_height"] as? Double,
                   let label = dict["label"] as? String {
                    let rect = NSRect(x: bboxX, y: bboxY, width: bboxWidth, height: bboxHeight)
                    window.highlightView.showBox(rect: rect, label: label)
                }
            case "hud_action":
                // HUD action update from Python overlay
                // entries: [{"action_type": "click", "target_label": "Send", "tier": "T1", "channel": "C2", "status": "verified", ...}, ...]
                // session_start_iso: "2026-05-01T10:00:00Z"
                // goal: "Compose email"
                if let entries = dict["entries"] as? [[String: Any]],
                   let sessionStart = dict["session_start_iso"] as? String,
                   let goal = dict["goal"] as? String {
                    var hudEntries: [HUDActionEntry] = []
                    for entryDict in entries {
                        if let actionType = entryDict["action_type"] as? String,
                           let targetLabel = entryDict["target_label"] as? String,
                           let tier = entryDict["tier"] as? String,
                           let channel = entryDict["channel"] as? String,
                           let status = entryDict["status"] as? String {
                            let entry = HUDActionEntry(
                                action_type: actionType,
                                target_label: targetLabel,
                                tier: tier,
                                channel: channel,
                                status: status
                            )
                            hudEntries.append(entry)
                        }
                    }
                    // Update HUD panel (assumes it's part of window's view hierarchy or accessible via VisualizerPanel)
                    window.updateHUDActions(hudEntries, sessionStart: sessionStart, goal: goal)
                }
            default:
                break
            }
        }
    }
}
