import AppKit
import QuartzCore

/// Ghost cursor view — renders circle + crosshair using NSView.draw(), NOT CALayer.
/// P12 mitigation: NSView.draw() has <1µs overhead vs CALayer which hits WindowServer CPU spike at >10/sec.
class GhostCursorView: NSView {
    private var targetX: Double = 0.0
    private var targetY: Double = 0.0
    private var startX: Double = 0.0
    private var startY: Double = 0.0
    private var animationProgress: Double = 0.0  // 0.0 = start, 1.0 = end
    private var displayLink: CVDisplayLink?
    private var rippleOpacity: Double = 0.0  // Fade ripple over 400ms
    private var animationFrameCount: Int = 0

    override func isOpaque() -> Bool { false }

    func animateToTarget(x: Double, y: Double, duration: Int) {
        self.targetX = x
        self.targetY = y
        self.animationProgress = 0.0
        self.rippleOpacity = 1.0

        // Get start position (current mouse location)
        let mouseLocation = NSEvent.mouseLocation
        self.startX = mouseLocation.x
        self.startY = mouseLocation.y

        // Create display link for 60fps animation
        startDisplayLink(duration: duration)
    }

    private func startDisplayLink(duration: Int) {
        // Create CVDisplayLink for smooth 60fps rendering
        var displayLink: CVDisplayLink?
        let status = CVDisplayLinkCreateWithActiveCGDisplay(&displayLink)
        guard status == kCVReturnSuccess, let link = displayLink else { return }

        let durationSeconds = Double(duration) / 1000.0
        animationFrameCount = Int(durationSeconds * 60.0)  // 60fps
        var frameIndex = 0

        CVDisplayLinkSetOutputCallback(link, { link, inNow, inOutputTime, flagsIn, flagsOut, displayLinkContext -> CVReturn in
            guard let contextPtr = displayLinkContext else { return kCVReturnError }
            let selfPtr = Unmanaged<GhostCursorView>.fromOpaque(contextPtr)
            let view = selfPtr.takeUnretainedValue()

            frameIndex += 1
            view.animationProgress = min(1.0, Double(frameIndex) / Double(view.animationFrameCount))

            DispatchQueue.main.async {
                view.setNeedsDisplay(view.bounds)  // Trigger redraw

                // Ripple fades over 400ms (separate curve)
                view.rippleOpacity = max(0.0, 1.0 - (view.animationProgress * 1.25))  // 1.25x = finishes at 80% progress
            }

            if frameIndex >= view.animationFrameCount {
                CVDisplayLinkStop(link)
            }

            return kCVReturnSuccess
        }, Unmanaged.passUnretained(self).toOpaque())

        self.displayLink = displayLink
        CVDisplayLinkStart(displayLink)
    }

    override func draw(_ dirtyRect: NSRect) {
        NSColor.clear.setFill()
        dirtyRect.fill()

        // Ease-in-out cubic interpolation (P12 — only called from draw())
        let t = easeInOutCubic(animationProgress)
        let lerpX = startX + (targetX - startX) * t
        let lerpY = startY + (targetY - startY) * t

        // Draw ghost cursor circle + crosshair
        drawGhostCursor(at: NSPoint(x: lerpX, y: lerpY))

        // Draw ripple (fades)
        if rippleOpacity > 0.0 {
            drawRipple(at: NSPoint(x: targetX, y: targetY), opacity: rippleOpacity)
        }
    }

    private func drawGhostCursor(at point: NSPoint) {
        // Circle: 16px diameter, 1px stroke, 80% opacity blue (UI-SPEC L61)
        let radius = 8.0
        let circlePath = NSBezierPath(ovalIn: NSRect(x: point.x - radius, y: point.y - radius, width: radius * 2, height: radius * 2))

        NSColor.systemBlue.withAlphaComponent(0.8).setStroke()
        circlePath.lineWidth = 1.0
        circlePath.stroke()

        // Crosshair: two 1px lines
        let lineLength = 6.0
        let hLine = NSBezierPath()
        hLine.move(to: NSPoint(x: point.x - lineLength, y: point.y))
        hLine.line(to: NSPoint(x: point.x + lineLength, y: point.y))
        hLine.lineWidth = 1.0
        hLine.stroke()

        let vLine = NSBezierPath()
        vLine.move(to: NSPoint(x: point.x, y: point.y - lineLength))
        vLine.line(to: NSPoint(x: point.x, y: point.y + lineLength))
        vLine.lineWidth = 1.0
        vLine.stroke()
    }

    private func drawRipple(at point: NSPoint, opacity: Double) {
        // Concentric ring, fades from opaque to transparent over 400ms (UI-SPEC L62)
        let rippleRadii = [16.0, 22.0, 28.0]  // Three expanding rings

        for (index, radius) in rippleRadii.enumerated() {
            let scaledRadius = radius * (1.0 + animationProgress * 0.5)  // Expand as it fades
            let scaledOpacity = opacity * (1.0 - Double(index) * 0.3)  // Inner rings fade faster

            let ripplePath = NSBezierPath(ovalIn: NSRect(x: point.x - scaledRadius, y: point.y - scaledRadius, width: scaledRadius * 2, height: scaledRadius * 2))
            NSColor.systemBlue.withAlphaComponent(scaledOpacity).setStroke()
            ripplePath.lineWidth = 1.0
            ripplePath.stroke()
        }
    }

    private func easeInOutCubic(_ t: Double) -> Double {
        // Cubic ease-in-out: Y = 3t² - 2t³ when t >= 0.5, else 4t³
        if t < 0.5 {
            return 4.0 * t * t * t
        } else {
            let f = 2.0 * t - 2.0
            return 0.5 * f * f * f + 1.0
        }
    }
}
