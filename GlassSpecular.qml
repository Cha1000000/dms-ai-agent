import QtQuick

// Highlight along the edge of a glass bubble: bright at the top left, fading
// out in the middle and coming back a little at the bottom right, the way light
// catches the rim of a lens. Fills its parent, which should be the bubble.
// Rendered with a screen-space antialiased SDF shader so scaled bubbles keep
// crisp, concentric corners.
ShaderEffect {
    id: spec

    property real radius: 16

    anchors.fill: parent
    fragmentShader: Qt.resolvedUrl("shaders/glass_specular.frag.qsb")

    property real widthPx: width
    property real heightPx: height
    property real radiusPx: radius
    property real strokePx: 1.2
}
