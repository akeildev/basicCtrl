import SwiftUI
import AppKit

/// SwiftUI HUD panel displaying last 8 actions with tier/channel badges, status icons, and controls.
/// UI-SPEC L106-160: 320px width, .ultraThinMaterial, opacity slider, position snap, Cmd+Shift+V hotkey.
/// Hosted in VisualizerPanel as NSHostingController.
struct HUDView: View {
    @State private var actionHistory: [HUDActionEntry] = []
    @State private var opacity: Double = 0.7
    @State private var position: HUDPosition = .bottomRight
    @State private var isVisible = true
    @State private var sessionStart = ""
    @State private var goal = ""
    @State private var scrollOffset: Int = 0

    var body: some View {
        VStack(spacing: 0) {
            // Header: Session timestamp + goal
            VStack(alignment: .leading, spacing: 4) {
                Text("Session: \(sessionStart)")
                    .font(.system(size: 12, weight: .regular, design: .default))
                    .foregroundColor(.black)
                Text("Goal: \(goal)")
                    .font(.system(size: 14, weight: .medium, design: .default))
                    .foregroundColor(.black)
            }
            .frame(maxWidth: .infinity, alignment: .leading)
            .padding(16)  // md spacing per UI-SPEC L114

            Divider()
                .frame(height: 1)
                .background(Color(red: 0.898, green: 0.898, blue: 0.898))  // #E5E5E5

            // Action history (last 8)
            ScrollView {
                VStack(spacing: 0) {
                    if actionHistory.isEmpty {
                        Text("(no actions yet)")
                            .font(.system(size: 12, weight: .regular, design: .default))
                            .foregroundColor(Color(red: 0.4, green: 0.4, blue: 0.4))  // #666666
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                    } else {
                        ForEach(0..<actionHistory.count, id: \.self) { idx in
                            HUDActionRow(entry: actionHistory[idx])
                            if idx < actionHistory.count - 1 {
                                Divider()
                                    .frame(height: 1)
                                    .background(Color(red: 0.898, green: 0.898, blue: 0.898))
                            }
                        }
                    }
                }
            }

            Divider()

            // Controls: prev/next buttons, opacity slider, snap toggle
            HStack(spacing: 8) {  // sm spacing per UI-SPEC L159
                Button(action: { scrollPrevious() }) {
                    Image(systemName: "chevron.left")
                        .font(.system(size: 12))
                        .foregroundColor(.black)
                }
                .buttonStyle(PlainButtonStyle())

                Button(action: { scrollNext() }) {
                    Image(systemName: "chevron.right")
                        .font(.system(size: 12))
                        .foregroundColor(.black)
                }
                .buttonStyle(PlainButtonStyle())

                Slider(value: $opacity, in: 0.3...1.0, step: 0.05)
                    .frame(maxWidth: 100)

                Button(action: { toggleSnap() }) {
                    Image(systemName: position == .bottomRight ? "pin.fill" : "pin")
                        .font(.system(size: 12))
                        .foregroundColor(.black)
                }
                .buttonStyle(PlainButtonStyle())
            }
            .padding(8)
        }
        .frame(width: 320)
        .background(Material.ultraThin)  // UI-SPEC L112
        .cornerRadius(12)  // UI-SPEC L114
        .opacity(opacity)
    }

    private func scrollPrevious() {
        if scrollOffset > 0 {
            scrollOffset -= 1
        }
    }

    private func scrollNext() {
        if scrollOffset < max(0, actionHistory.count - 8) {
            scrollOffset += 1
        }
    }

    private func toggleSnap() {
        // Cycle through positions: bottomRight → topRight → bottomLeft → topLeft → bottomRight
        switch position {
        case .bottomRight:
            position = .topRight
        case .topRight:
            position = .bottomLeft
        case .bottomLeft:
            position = .topLeft
        case .topLeft:
            position = .bottomRight
        case .center:
            position = .bottomRight
        }
    }

    /// Called by Visualizer.swift to update action history
    mutating func updateActions(_ newActions: [HUDActionEntry]) {
        self.actionHistory = newActions
    }

    /// Called by Visualizer.swift to update session metadata
    mutating func setSessionMetadata(sessionStart: String, goal: String) {
        self.sessionStart = sessionStart
        self.goal = goal
    }
}

struct HUDActionRow: View {
    let entry: HUDActionEntry

    var tierColor: Color {
        switch entry.tier {
        case "T1": return Color(red: 0, green: 0.47, blue: 1.0)  // #007AFF — blue
        case "T2": return Color(red: 0.196, green: 0.706, blue: 0.976)  // #32B4F9 — cyan
        case "T3": return Color(red: 1.0, green: 0.584, blue: 0)  // #FF9500 — orange
        case "T4": return Color(red: 0.204, green: 0.784, blue: 0.349)  // #34C759 — green
        case "T5": return Color(red: 1.0, green: 0.231, blue: 0.188)  // #FF3B30 — red
        default: return .gray
        }
    }

    var statusSymbol: String {
        switch entry.status {
        case "verified": return "✓"
        case "healing": return "⚠"
        case "failed": return "✗"
        default: return "?"
        }
    }

    var statusColor: Color {
        switch entry.status {
        case "verified": return .green
        case "healing": return .orange
        case "failed": return .red
        default: return .gray
        }
    }

    var body: some View {
        HStack(spacing: 0) {
            // Tier badge: T1-T5 in monospace, 11px, semibold, tier color
            Text(entry.tier)
                .font(.system(size: 11, weight: .semibold, design: .monospaced))
                .foregroundColor(tierColor)
                .frame(width: 20)

            Spacer().frame(width: 8)  // xs spacing

            // Action text: action_type + target_label (truncated at 40 chars)
            Text(entry.action_type + " " + (entry.target_label.count > 0 ? "\"\(entry.target_label)\"" : ""))
                .font(.system(size: 12, weight: .regular, design: .monospaced))
                .foregroundColor(.black)
                .lineLimit(1)

            Spacer()

            // Status icon + channel badge
            HStack(spacing: 4) {
                Text(statusSymbol)
                    .font(.system(size: 12, weight: .regular))
                    .foregroundColor(statusColor)

                Text(entry.channel)
                    .font(.system(size: 10, weight: .medium, design: .monospaced))
                    .foregroundColor(Color(red: 0.4, green: 0.4, blue: 0.4))  // #666666
            }
        }
        .frame(height: 44)  // tap-friendly per UI-SPEC L149
        .padding(.horizontal, 12)
    }
}

enum HUDPosition {
    case bottomRight
    case topRight
    case bottomLeft
    case topLeft
    case center
}

struct HUDActionEntry: Identifiable, Hashable {
    let id: UUID = UUID()
    let action_type: String
    let target_label: String
    let tier: String
    let channel: String
    let status: String

    func hash(into hasher: inout Hasher) {
        hasher.combine(id)
    }

    static func == (lhs: HUDActionEntry, rhs: HUDActionEntry) -> Bool {
        lhs.id == rhs.id
    }
}

#Preview {
    HUDView()
}
