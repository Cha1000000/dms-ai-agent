import QtQuick
import QtQuick.Effects

// Neon gradient rim for a rounded card. Must be a sibling of the target.
//
// Solid cards: a gradient plate slightly larger than the target peeks out
// around its edges as a ring, and a blurred copy of the plate underneath gives
// the glow. A translucent card would show the whole plate through itself, so
// with `ring` set only the outline is drawn: it is softened and brightened a
// little, and its blurred copy gives the glow.
Item {
    id: neon

    property Item target
    property real radius: 20
    property real thickness: 2
    property real glowOpacity: 0.6
    property bool ring: false

    visible: target ? target.visible && AgentTheme.neonEnabled : false
    z: target ? target.z - 1 : 0
    anchors.fill: target
    anchors.margins: -thickness

    Rectangle {
        id: rim
        visible: !neon.ring
        anchors.fill: parent
        radius: neon.radius + neon.thickness
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: AgentTheme.neon0 }
            GradientStop { position: 0.35; color: AgentTheme.neon1 }
            GradientStop { position: 0.7; color: AgentTheme.neon2 }
            GradientStop { position: 1.0; color: AgentTheme.neon3 }
        }
    }

    MultiEffect {
        visible: !neon.ring
        source: rim
        anchors.fill: rim
        z: -1
        blurEnabled: true
        blurMax: 24
        blur: 1.0
        opacity: neon.glowOpacity
    }

    // The ring variant: only built while it is in use, so the default look costs nothing extra.
    Loader {
        active: neon.ring && AgentTheme.neonEnabled
        anchors.fill: parent
        sourceComponent: Item {
            // Painted into a texture only; what is shown are the two effects below.
            ShaderEffect {
                id: ringSdf
                visible: false
                anchors.fill: parent
                fragmentShader: Qt.resolvedUrl("shaders/neon_ring.frag.qsb")

                property real widthPx: width
                property real heightPx: height
                property real radiusPx: neon.radius + neon.thickness
                property real thicknessPx: neon.thickness
                property vector4d neon0: Qt.vector4d(AgentTheme.neon0.r, AgentTheme.neon0.g, AgentTheme.neon0.b, AgentTheme.neon0.a)
                property vector4d neon1: Qt.vector4d(AgentTheme.neon1.r, AgentTheme.neon1.g, AgentTheme.neon1.b, AgentTheme.neon1.a)
                property vector4d neon2: Qt.vector4d(AgentTheme.neon2.r, AgentTheme.neon2.g, AgentTheme.neon2.b, AgentTheme.neon2.a)
                property vector4d neon3: Qt.vector4d(AgentTheme.neon3.r, AgentTheme.neon3.g, AgentTheme.neon3.b, AgentTheme.neon3.a)
            }

            MultiEffect {
                source: ringSdf
                anchors.fill: ringSdf
                blurEnabled: true
                blurMax: 20
                blur: 1.0
                saturation: 0.6
                brightness: 0.2
            }

            MultiEffect {
                source: ringSdf
                anchors.fill: ringSdf
                z: -1
                blurEnabled: true
                blurMax: 24
                blur: 1.0
                brightness: 0.4
                opacity: 0.5
            }
        }
    }
}
