import AppKit
import QuartzCore

/// Element highlight overlay — single CAShapeLayer per element, hidden during verifier windows.
/// P11 mitigation: single CAShapeLayer (not multiple), hidden via opacity 0 instead of remove/re-add.
class HighlightOverlayView: NSView {
    private var highlightLayer: CAShapeLayer?
    private var labelLayer: CATextLayer?
    private var hideTimer: Timer?

    override init(frame frameRect: NSRect) {
        super.init(frame: frameRect)
        setup()
    }

    required init?(coder: NSCoder) {
        super.init(coder: coder)
        setup()
    }

    private func setup() {
        // Use native Core Animation but minimize layer count (P11)
        self.layer = CALayer()
        self.wantsLayer = true
    }

    func showBox(rect: NSRect, label: String) {
        // Create or reuse single CAShapeLayer (P11 — single layer per element)
        if highlightLayer == nil {
            highlightLayer = CAShapeLayer()
            self.layer?.addSublayer(highlightLayer!)
        }

        guard let layer = highlightLayer else { return }

        // Rounded rectangle path: 8px corner radius (UI-SPEC L91)
        let path = NSBezierPath(roundedRect: rect, xRadius: 8, yRadius: 8)
        layer.path = path.cgPath

        // 2px accent-blue border, 60% opacity (UI-SPEC L91)
        layer.strokeColor = NSColor.systemBlue.withAlphaComponent(0.6).cgColor
        layer.lineWidth = 2.0

        // 10% fill with accent blue (UI-SPEC L91)
        layer.fillColor = NSColor.systemBlue.withAlphaComponent(0.1).cgColor

        // Label overlay: top-left corner, 4px inset (UI-SPEC L92)
        setupLabelLayer(text: label, inRect: rect)

        // Show box (opacity 1.0)
        layer.opacity = 1.0

        // Auto-hide after 300ms + ripple duration (UI-SPEC L100-101)
        scheduleHide(duration: 300)
    }

    private func setupLabelLayer(text: String, inRect rect: NSRect) {
        // Create or reuse label
        if labelLayer == nil {
            labelLayer = CATextLayer()
            labelLayer?.font = NSFont(name: "SF Mono", size: 11)?.fontName as CFString?
            labelLayer?.fontSize = 11
            labelLayer?.foregroundColor = NSColor.white.cgColor
            self.layer?.addSublayer(labelLayer!)
        }

        guard let label = labelLayer else { return }

        // Truncate label to 40 chars (UI-SPEC L145)
        let truncated = String(text.prefix(40))
        label.string = truncated

        // Position: top-left, 4px inset (UI-SPEC L92)
        label.frame = CGRect(x: rect.minX + 4, y: rect.maxY - 4 - 11, width: 200, height: 16)

        // Set text color explicitly
        label.foregroundColor = NSColor.white.cgColor
    }

    func hideBox(immediately: Bool = false) {
        hideTimer?.invalidate()

        if immediately {
            highlightLayer?.opacity = 0
            labelLayer?.opacity = 0
        } else {
            // Fade over 200ms
            CATransaction.begin()
            CATransaction.setCompletionBlock { [weak self] in
                self?.highlightLayer?.opacity = 0
            }
            let animation = CABasicAnimation(keyPath: "opacity")
            animation.fromValue = highlightLayer?.opacity ?? 1.0
            animation.toValue = 0.0
            animation.duration = 0.2
            highlightLayer?.add(animation, forKey: "fadeOut")
            CATransaction.commit()
        }
    }

    private func scheduleHide(duration: Int) {
        hideTimer?.invalidate()
        hideTimer = Timer.scheduledTimer(withTimeInterval: TimeInterval(duration) / 1000.0, repeats: false) { [weak self] _ in
            self?.hideBox()
        }
    }

    func hideAllLayers() {
        // Called during verifier window (screenshot) capture
        highlightLayer?.opacity = 0  // P11: hide, don't remove
        labelLayer?.opacity = 0
    }

    func showAllLayers() {
        // Called after verifier window capture
        if highlightLayer?.opacity == 0 {
            highlightLayer?.opacity = 1.0
            labelLayer?.opacity = 1.0
        }
    }
}
