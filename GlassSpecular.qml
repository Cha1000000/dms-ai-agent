import QtQuick

// Highlight along the edge of a glass bubble: bright at the top left, fading
// out in the middle and coming back a little at the bottom right, the way light
// catches the rim of a lens. Fills its parent, which should be the bubble.
Canvas {
    id: spec

    property real radius: 16

    anchors.fill: parent

    onRadiusChanged: requestPaint()
    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()

    onPaint: {
        var c = getContext("2d");
        c.reset();
        if (width < 2 || height < 2) return;
        var g = c.createLinearGradient(0, 0, width, height);
        g.addColorStop(0.0, "rgba(255,255,255,0.75)");
        g.addColorStop(0.25, "rgba(255,255,255,0.18)");
        g.addColorStop(0.6, "rgba(255,255,255,0.04)");
        g.addColorStop(1.0, "rgba(255,255,255,0.35)");
        c.strokeStyle = g;
        c.lineWidth = 1.2;
        c.beginPath();
        c.roundedRect(0.6, 0.6, width - 1.2, height - 1.2, radius, radius);
        c.stroke();
    }
}
