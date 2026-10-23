import QtQuick
import QtQuick.Effects
import org.kde.kirigami as Kirigami

Item {
    id: art
    property url source
    property real cornerRadius: 24
    readonly property bool ready: image.status === Image.Ready

    Rectangle {
        anchors.fill: parent
        radius: art.cornerRadius
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.rgba(0.25, 0.66, 0.85, 0.24)) }
            GradientStop { position: 1; color: Qt.tint(Kirigami.Theme.backgroundColor, Qt.rgba(0.5, 0.4, 0.7, 0.14)) }
        }
        border.color: Qt.rgba(1, 1, 1, 0.12)
        Kirigami.Icon {
            anchors.centerIn: parent
            width: parent.width * 0.34
            height: width
            source: "media-optical-audio"
            opacity: 0.3
            visible: !art.ready
        }
    }
    Image {
        id: image
        anchors.fill: parent
        source: art.source
        sourceSize: Qt.size(Math.ceil(art.width * Screen.devicePixelRatio), Math.ceil(art.height * Screen.devicePixelRatio))
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        visible: false
    }
    Rectangle {
        id: mask
        anchors.fill: parent
        radius: art.cornerRadius
        visible: false
        layer.enabled: true
    }
    MultiEffect {
        anchors.fill: parent
        source: image
        visible: art.ready
        autoPaddingEnabled: false
        maskEnabled: true
        maskSource: mask
    }
    Rectangle {
        anchors.fill: parent
        radius: art.cornerRadius
        color: "transparent"
        border.color: Qt.rgba(1, 1, 1, 0.15)
        border.width: 1
    }
}
