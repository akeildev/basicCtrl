import SwiftUI

/// CounterfactualOverlayView renders alternate recovery branch outcomes as dashed paths.
///
/// When a recovery branch loses in a race (Phase 3) or a translator channel loses
/// in a race (Phase 2), we visualize it as a dashed purple line diverging from
/// the primary timeline at the decision point.
///
/// Properties:
/// - branchName: Identifier (e.g., "B1", "T2/C5", "RECOVERY")
/// - dashedPath: List of CGPoint in screen coordinates from Timeline3D projection
/// - opacity: Semi-transparency for post-divergence state (default 0.4)
struct CounterfactualOverlayView: View {
    let branchName: String
    let dashedPath: [CGPoint]
    let opacity: Double = 0.4

    var body: some View {
        Canvas { context, size in
            // Draw dashed line for alternate path
            var path = Path()
            for (i, point) in dashedPath.enumerated() {
                if i == 0 {
                    path.move(to: point)
                } else {
                    path.addLine(to: point)
                }
            }

            // Dashed stroke in purple, semi-transparent
            context.stroke(
                path,
                with: .color(.purple.opacity(opacity)),
                lineWidth: 2.0,
                dash: [4, 4]  // Dashed pattern: 4px on, 4px off
            )

            // Overlay label at divergence point
            let labelText = Text("Branch \(branchName)")
                .font(.system(size: 11, weight: .medium))
                .foregroundColor(.purple)

            if let firstPoint = dashedPath.first {
                context.draw(labelText, at: firstPoint, anchor: .topLeading)
            }
        }
        .frame(maxWidth: .infinity, maxHeight: .infinity)
    }
}

/// CounterfactualPathBuilder — helper to construct dashed paths for counterfactual branches.
///
/// Transforms a list of (x, y) tuples from Python Timeline3D into Canvas-ready CGPoints.
struct CounterfactualPathBuilder {
    /// Build CGPoint array from (float, float) tuples (screen coords from Timeline3D projection).
    ///
    /// - Parameter projectedCoords: List of (x, y) screen coordinates
    /// - Returns: Array of CGPoint suitable for Canvas path drawing
    static func buildPath(from projectedCoords: [(Double, Double)]) -> [CGPoint] {
        return projectedCoords.map { CGPoint(x: $0.0, y: $0.1) }
    }

    /// Build a path segment from divergence point to cancellation point.
    ///
    /// Used when we have only the divergence point and final cancellation point
    /// (linear interpolation for now; future could add bezier curves).
    ///
    /// - Parameters:
    ///   - start: Divergence point in screen coords
    ///   - end: Cancellation point in screen coords
    ///   - stepCount: Number of intermediate points to generate
    /// - Returns: Linear path from start to end
    static func buildLinearPath(
        from start: CGPoint,
        to end: CGPoint,
        stepCount: Int = 10
    ) -> [CGPoint] {
        var path: [CGPoint] = [start]

        for i in 1...stepCount {
            let t = Double(i) / Double(stepCount)
            let x = start.x + (end.x - start.x) * t
            let y = start.y + (end.y - start.y) * t
            path.append(CGPoint(x: x, y: y))
        }

        return path
    }
}

/// CounterfactualTimelineView — full counterfactual visualization.
///
/// Integrates with Timeline3D from basicctrl/replay/timeline.py to render
/// both primary action path and counterfactual branches (losers from races).
///
/// Usage:
/// ```swift
/// @State var counterfactualEvents: [CounterfactualEvent] = []
/// CounterfactualTimelineView(
///     branches: counterfactualEvents,
///     dashedPathOpacity: 0.4,
///     isVisible: $showCounterfactual
/// )
/// ```
struct CounterfactualTimelineView: View {
    let branches: [CounterfactualBranch]
    let dashedPathOpacity: Double
    @Binding var isVisible: Bool

    var body: some View {
        ZStack {
            // Background (transparent)
            Color.clear

            // Render each counterfactual branch as a dashed overlay
            ForEach(branches, id: \.id) { branch in
                CounterfactualOverlayView(
                    branchName: branch.name,
                    dashedPath: branch.dashedPath,
                    opacity: dashedPathOpacity
                )
            }
        }
        .opacity(isVisible ? 1.0 : 0.0)
        .animation(.easeInOut(duration: 0.3), value: isVisible)
    }
}

/// CounterfactualBranch — data model for rendering one alternate branch.
///
/// Corresponds to Python CounterfactualEvent.
struct CounterfactualBranch: Identifiable {
    let id: String  // Unique ID for ForEach
    let name: String  // Branch name (e.g., "B1", "T2/C5")
    let dashedPath: [CGPoint]  // Screen coordinates from Timeline3D.project_to_2d()
    let whyLost: String  // "cancelled", "timeout", "verifier_rejected"
    let stepIndex: Int  // Step where branch was lost
}

// MARK: - Preview

#Preview {
    let sampleBranches: [CounterfactualBranch] = [
        CounterfactualBranch(
            id: "b1",
            name: "B1",
            dashedPath: [
                CGPoint(x: 100, y: 100),
                CGPoint(x: 150, y: 150),
                CGPoint(x: 200, y: 180),
            ],
            whyLost: "cancelled",
            stepIndex: 3
        ),
        CounterfactualBranch(
            id: "t2c5",
            name: "T2/C5",
            dashedPath: [
                CGPoint(x: 100, y: 100),
                CGPoint(x: 140, y: 130),
                CGPoint(x: 170, y: 160),
            ],
            whyLost: "timeout",
            stepIndex: 2
        ),
    ]

    CounterfactualTimelineView(
        branches: sampleBranches,
        dashedPathOpacity: 0.4,
        isVisible: .constant(true)
    )
    .frame(width: 400, height: 300)
    .border(Color.gray)
}
