import QtQuick

// The glass body of a bubble: its tint and edge highlight, drawn over the part
// of the bubble that is inside the feed. A bubble cut by the edge of the feed
// keeps rounded corners at the cut, matching the blur patch the compositor
// draws there (a lens is always rounded; a square cut would leave tinted
// corners with no glass behind them). Fills its parent, which should be a
// Loader filling the bubble.
Item {
    id: tint

    required property Item chat
    required property Rectangle bubble
    property color color
    // Same radius as the bubble, which is also what the blur patch uses.
    readonly property real radius: bubble.radius

    anchors.fill: parent

    readonly property rect part: { chat.glassTick; return chat.glassPart(bubble); }

    Rectangle {
        id: body
        x: tint.part.x; y: tint.part.y
        width: tint.part.width; height: tint.part.height
        visible: height > 0 && width > 0
        radius: Math.min(tint.radius, height / 2)
        color: tint.color

        GlassSpecular { radius: body.radius }
    }
}
