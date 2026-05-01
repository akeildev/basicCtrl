import SwiftUI

/// Represents a single row in the diff view (common, added, removed, changed, heal).
struct DiffItem: Identifiable {
    let id: UUID = UUID()
    let kind: String  // "common", "healed", "added", "removed", "changed"
    let actionA: [String: Any]?
    let actionB: [String: Any]?
    let beforeVerdict: String?
    let afterVerdict: String?
    let healReason: String?

    var markerColor: Color {
        switch kind {
        case "common":
            return .gray
        case "healed", "changed":
            return .orange
        case "added":
            return .green
        case "removed":
            return .red
        default:
            return .gray
        }
    }

    var markerText: String {
        switch kind {
        case "common":
            return "SAME"
        case "healed":
            return "HEAL"
        case "changed":
            return "CHG"
        case "added":
            return "NEW"
        case "removed":
            return "DEL"
        default:
            return "?"
        }
    }
}

/// Side-by-side session diff view — compares two action logs.
struct SessionDiffView: View {
    let diffItems: [DiffItem]

    @State private var showOnlyDiffs = false
    @State private var scrollAnchor: UUID?

    var body: some View {
        VStack(spacing: 0) {
            // Header
            HStack {
                Text("Session A")
                    .font(.system(size: 12, weight: .semibold))
                Spacer()
                Text("Diff")
                    .font(.system(size: 11, weight: .medium))
                    .frame(width: 50)
                Spacer()
                Text("Session B")
                    .font(.system(size: 12, weight: .semibold))
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
            .background(Color(white: 0.95))

            // Divider
            Divider()

            // Diff content
            ScrollView {
                VStack(alignment: .leading, spacing: 0) {
                    ForEach(diffItems) { item in
                        if !showOnlyDiffs || item.kind != "common" {
                            diffRow(item)
                        }
                    }
                }
            }

            Divider()

            // Controls
            HStack(spacing: 12) {
                Button(action: { showOnlyDiffs.toggle() }) {
                    Image(systemName: "line.3.horizontal.decrease.circle")
                    Text("Diffs only")
                        .font(.system(size: 11))
                }
                .buttonStyle(.bordered)

                Spacer()
            }
            .padding(.horizontal, 12)
            .padding(.vertical, 8)
        }
    }

    @ViewBuilder
    private func diffRow(_ item: DiffItem) -> some View {
        VStack(alignment: .leading, spacing: 0) {
            HStack(alignment: .top, spacing: 0) {
                // Session A (left)
                VStack(alignment: .leading, spacing: 2) {
                    if let action = item.actionA {
                        actionRowContent(action)
                    } else {
                        Text("(removed)")
                            .font(.system(size: 11))
                            .foregroundColor(.gray)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)

                // Marker (center)
                VStack(alignment: .center, spacing: 0) {
                    Text(item.markerText)
                        .font(.system(size: 10, weight: .semibold, design: .monospaced))
                        .foregroundColor(item.markerColor)
                    if item.kind == "healed", let reason = item.healReason {
                        Text(reason)
                            .font(.system(size: 8, weight: .regular))
                            .foregroundColor(.orange)
                    }
                }
                .frame(width: 50)

                // Session B (right)
                VStack(alignment: .leading, spacing: 2) {
                    if let action = item.actionB {
                        actionRowContent(action)
                    } else {
                        Text("(added)")
                            .font(.system(size: 11))
                            .foregroundColor(.gray)
                    }
                }
                .frame(maxWidth: .infinity, alignment: .leading)
                .padding(.horizontal, 8)
                .padding(.vertical, 6)
            }
            .background(backgroundColor(for: item.kind))

            // Divider between rows
            Divider()
                .padding(.leading, 8)
        }
    }

    @ViewBuilder
    private func actionRowContent(_ action: [String: Any]) -> some View {
        HStack(spacing: 4) {
            // Tier badge
            if let tier = action["tier"] as? String {
                Text(tier)
                    .font(.system(size: 10, weight: .semibold, design: .monospaced))
                    .foregroundColor(.blue)
            }

            // Action type
            if let type = action["action_type"] as? String {
                Text(type)
                    .font(.system(size: 11, weight: .regular, design: .monospaced))
                    .foregroundColor(.black)
            }

            // Target label
            if let label = action["target_label"] as? String {
                Text(""\(label)"")
                    .font(.system(size: 10, weight: .regular))
                    .foregroundColor(.gray)
                    .lineLimit(1)
            }

            Spacer()
        }
    }

    private func backgroundColor(for kind: String) -> Color {
        switch kind {
        case "common":
            return .white
        case "healed":
            return Color(white: 0.98)
        case "changed":
            return Color(white: 0.97)
        case "added":
            return Color(green: 0.98)
        case "removed":
            return Color(red: 0.98)
        default:
            return .white
        }
    }
}

// Preview
#if DEBUG
struct SessionDiffView_Previews: PreviewProvider {
    static var previews: some View {
        let sampleDiffs = [
            DiffItem(kind: "common", actionA: ["tier": "T1", "action_type": "click", "target_label": "inbox"], actionB: ["tier": "T1", "action_type": "click", "target_label": "inbox"], beforeVerdict: nil, afterVerdict: nil, healReason: nil),
            DiffItem(kind: "healed", actionA: ["tier": "T3", "action_type": "type", "target_label": "subject"], actionB: ["tier": "T1", "action_type": "type", "target_label": "subject"], beforeVerdict: "failed", afterVerdict: "verified", healReason: "T3→T1"),
            DiffItem(kind: "added", actionA: nil, actionB: ["tier": "T2", "action_type": "scroll", "target_label": "body"], beforeVerdict: nil, afterVerdict: nil, healReason: nil),
        ]

        SessionDiffView(diffItems: sampleDiffs)
            .frame(width: 800, height: 400)
    }
}
#endif
