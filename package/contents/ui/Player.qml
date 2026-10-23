import "Locale.js" as L10n
import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import QtQuick.Effects
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC
import org.kde.plasma.plasmoid

Item {
    id: player
    required property var controller
    property bool choosingDevice: false
    readonly property bool effectsActive: controller.expanded && !choosingDevice && !controller.reducedMotion
    readonly property var device: controller.device
    readonly property color ink: Kirigami.Theme.textColor
    readonly property color secondaryInk: Qt.rgba(ink.r, ink.g, ink.b, 0.6)
    implicitWidth: 352
    implicitHeight: controller.errorText || controller.sleepRemaining > 0 ? 420 : 392
    Layout.minimumWidth: 332
    Layout.minimumHeight: implicitHeight
    Layout.preferredWidth: 352
    Layout.preferredHeight: implicitHeight
    focus: true

    Keys.onSpacePressed: if (controller.active) controller.send("toggle")
    Keys.onRightPressed: if (device.can_next) controller.send("next")
    Keys.onLeftPressed: if (device.can_previous) controller.send("previous")
    Keys.onEscapePressed: choosingDevice = false

    Rectangle {
        anchors.fill: parent
        anchors.margins: 4
        radius: 18
        color: Qt.rgba(Kirigami.Theme.backgroundColor.r, Kirigami.Theme.backgroundColor.g,
                       Kirigami.Theme.backgroundColor.b, Plasmoid.configuration.glassOpacity)
        border.color: Qt.rgba(1, 1, 1, 0.12)
        border.width: 1
    }
    Image {
        id: glowSource
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: parent.width * 0.6
        height: width
        source: player.effectsActive ? device.artwork || "" : ""
        sourceSize: Qt.size(96, 96)
        fillMode: Image.PreserveAspectCrop
        visible: false
        asynchronous: true
    }
    MultiEffect {
        anchors.fill: glowSource
        source: glowSource
        blurEnabled: true
        blurMax: 64
        blur: 1
        saturation: 0.15
        opacity: 0.13
        visible: player.effectsActive && glowSource.status === Image.Ready
    }
    Rectangle {
        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
        anchors.margins: 5
        height: parent.height * 0.26
        radius: 17
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0.065) }
            GradientStop { position: 1; color: "transparent" }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 8
        visible: !player.choosingDevice

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Image { source: Qt.resolvedUrl("../icons/kcromecast.svg"); Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
            PC.Label {
                text: "KCromecast"
                font.weight: Font.DemiBold
                font.pixelSize: 13
                Layout.fillWidth: true
            }
            GlassButton {
                glyph: "view-refresh"
                hint: L10n.tr(Qt.locale(), "Refresh")
                quiet: true
                implicitWidth: 28
                onClicked: controller.refresh()
                visible: !controller.online
            }
            GlassButton {
                id: moreButton
                glyph: "view-more-symbolic"
                hint: L10n.tr(Qt.locale(), "More controls")
                quiet: true
                implicitWidth: 28
                onClicked: moreMenu.popup()
            }
        }

        QQC.AbstractButton {
            id: outputButton
            Layout.fillWidth: true
            implicitHeight: 42
            hoverEnabled: true
            onClicked: player.choosingDevice = true
            Accessible.name: L10n.tr(Qt.locale(), "Choose speakers")
            background: Rectangle {
                radius: 12
                color: Qt.rgba(1, 1, 1, outputButton.hovered ? 0.1 : 0.045)
                border.color: Qt.rgba(1, 1, 1, 0.09)
            }
            contentItem: RowLayout {
                spacing: 10
                Kirigami.Icon { source: device.group ? "audio-speakers-symbolic" : "network-wireless-symbolic"; Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    PC.Label { text: device.name || L10n.tr(Qt.locale(), "Choose speakers"); font.pixelSize: 12; font.weight: Font.DemiBold; Layout.fillWidth: true; elide: Text.ElideRight }
                    RowLayout {
                        spacing: 4
                        Image {
                            visible: device.service === "spotify"
                            source: Qt.resolvedUrl("../icons/spotify.svg")
                            Layout.preferredWidth: 10; Layout.preferredHeight: 10
                        }
                        PC.Label { text: controller.available ? (device.app || L10n.tr(Qt.locale(), "Ready to play"))
                            : controller.online ? (device.connection === "CONNECTING" ? L10n.tr(Qt.locale(), "Reconnecting…") : L10n.tr(Qt.locale(), "Speakers unavailable"))
                            : controller.hadConnection ? L10n.tr(Qt.locale(), "Reconnecting…") : L10n.tr(Qt.locale(), "Connecting…"); color: player.secondaryInk; font.pixelSize: 10 }
                    }
                }
                Rectangle { width: 6; height: 6; radius: 3; color: controller.available ? "#78d9b0" : player.secondaryInk }
                Kirigami.Icon { source: "arrow-down"; Layout.preferredWidth: 14; Layout.preferredHeight: 14; color: player.secondaryInk }
            }
            leftPadding: 14
            rightPadding: 14
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 88
            spacing: 14
            Artwork {
                Layout.preferredWidth: 88
                Layout.preferredHeight: 88
                cornerRadius: 15
                source: controller.expanded && controller.active ? device.artwork || "" : ""
                scale: controller.active && device.state === "PAUSED" && !controller.reducedMotion ? 0.96 : 1
                Behavior on scale { NumberAnimation { duration: controller.reducedMotion ? 0 : 180; easing.type: Easing.OutCubic } }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 5
                SelectableText {
                    Layout.fillWidth: true
                    trackTitle: controller.active ? device.title || "" : ""
                    trackArtist: device.artist || ""
                    text: controller.active ? device.title || L10n.tr(Qt.locale(), "Playing on your speakers")
                        : !controller.online ? L10n.tr(Qt.locale(), "Connecting to your music") : L10n.tr(Qt.locale(), "Start with your phone")
                    font.pixelSize: 16
                    font.weight: Font.DemiBold
                    maximumLines: 2
                }
                SelectableText {
                    Layout.fillWidth: true
                    trackTitle: controller.active ? device.title || "" : ""
                    trackArtist: device.artist || ""
                    text: controller.active ? device.artist || device.app || ""
                        : L10n.tr(Qt.locale(), "Cast music to these speakers, then control it here.")
                    color: player.secondaryInk
                    font.pixelSize: 11
                    maximumLines: controller.active ? 1 : 2
                }
                SelectableText {
                    Layout.fillWidth: true
                    trackTitle: controller.active ? device.title || "" : ""
                    trackArtist: device.artist || ""
                    visible: controller.active && !!device.album && device.album !== device.title
                    text: device.album || ""
                    font.pixelSize: 10
                    color: player.secondaryInk
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            spacing: -4
            QQC.Slider {
                id: seek
                Layout.fillWidth: true
                from: 0
                to: Math.max(1, device.duration || 0)
                property real pendingValue: 0
                enabled: controller.active && !!device.can_seek && !controller.busy
                onMoved: { pendingValue = value; if (!pressed) seekCommit.restart(); }
                onPressedChanged: {
                    if (pressed) pendingValue = value;
                    else if (enabled) { seekCommit.stop(); controller.send("seek", pendingValue); }
                }
                Accessible.name: L10n.tr(Qt.locale(), "Playback position")
                Binding { target: seek; property: "value"; when: !seek.pressed && !seekCommit.running; value: Math.min(seek.to, controller.playbackPosition) }
                Timer { id: seekCommit; interval: 350; onTriggered: if (!seek.pressed) controller.send("seek", seek.pendingValue) }
            }
            RowLayout {
                Layout.fillWidth: true
                PC.Label { text: controller.formatTime(seek.pressed ? seek.value : controller.playbackPosition); color: player.secondaryInk; font.pixelSize: 10; font.family: "monospace" }
                Item { Layout.fillWidth: true }
                PC.Label { text: device.duration ? controller.formatTime(device.duration) : "—:—"; color: player.secondaryInk; font.pixelSize: 10; font.family: "monospace" }
            }
        }

        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: 20
            GlassButton {
                glyph: "media-skip-backward"
                hint: L10n.tr(Qt.locale(), "Previous track")
                quiet: true
                enabled: controller.active && !!device.can_previous && !controller.busy
                onClicked: controller.send("previous")
            }
            GlassButton {
                prominent: true
                implicitWidth: 52
                padding: 14
                glyph: controller.playing ? "media-playback-pause" : "media-playback-start"
                hint: controller.playing ? L10n.tr(Qt.locale(), "Pause") : L10n.tr(Qt.locale(), "Play")
                enabled: controller.available && (device.state === "PAUSED" || !!device.can_pause) && (controller.active || device.transport === "spotify") && !controller.busy
                onClicked: controller.send("toggle")
            }
            GlassButton {
                glyph: "media-skip-forward"
                hint: L10n.tr(Qt.locale(), "Next track")
                quiet: true
                enabled: controller.active && !!device.can_next && !controller.busy
                onClicked: controller.send("next")
            }
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            GlassButton {
                implicitWidth: 28
                quiet: true
                glyph: device.muted ? "audio-volume-muted" : device.volume > 65 ? "audio-volume-high" : "audio-volume-low"
                hint: device.muted ? L10n.tr(Qt.locale(), "Unmute") : L10n.tr(Qt.locale(), "Mute")
                enabled: controller.available && device.transport !== "spotify"
                onClicked: controller.send("mute")
            }
            QQC.Slider {
                id: volume
                Layout.fillWidth: true
                from: 0; to: 100
                property real pendingValue: 0
                enabled: controller.available && device.can_volume !== false
                Accessible.name: L10n.tr(Qt.locale(), "Volume")
                onMoved: { pendingValue = value; if (!pressed) volumeCommit.restart(); }
                onPressedChanged: {
                    if (pressed) pendingValue = value;
                    else if (enabled) { volumeCommit.stop(); controller.send("volume", Math.round(pendingValue)); }
                }
                Keys.onLeftPressed: { value = Math.max(0, value - 1); pendingValue = value; volumeCommit.restart(); }
                Keys.onRightPressed: { value = Math.min(100, value + 1); pendingValue = value; volumeCommit.restart(); }
                Binding { target: volume; property: "value"; when: !volume.pressed && !volumeCommit.running; value: player.device.volume || 0 }
                Timer { id: volumeCommit; interval: 180; onTriggered: controller.send("volume", Math.round(volume.pendingValue)) }
            }
            PC.Label {
                Layout.preferredWidth: 30
                horizontalAlignment: Text.AlignRight
                text: Math.round(volume.pressed ? volume.value : device.volume || 0) + "%"
                font.pixelSize: 11
                color: player.secondaryInk
            }
        }

        PC.Label {
            Layout.fillWidth: true
            visible: controller.errorText.length > 0 || controller.sleepRemaining > 0
            text: controller.errorText || L10n.tr(Qt.locale(), "Sleep in %1", controller.formatTime(controller.sleepRemaining))
            color: controller.errorText ? Kirigami.Theme.negativeTextColor : Kirigami.Theme.highlightColor
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
        PC.Label {
            Layout.fillWidth: true
            text: L10n.tr(Qt.locale(), "Middle-click: pause · Scroll: volume")
            color: player.secondaryInk
            font.pixelSize: 10
            wrapMode: Text.WordWrap
            horizontalAlignment: Text.AlignHCenter
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 16
        spacing: 10
        visible: player.choosingDevice
        RowLayout {
            GlassButton { glyph: "go-previous"; hint: L10n.tr(Qt.locale(), "Back"); quiet: true; onClicked: player.choosingDevice = false }
            PC.Label { text: L10n.tr(Qt.locale(), "Your speakers"); font.pixelSize: 16; font.weight: Font.DemiBold; Layout.fillWidth: true }
            GlassButton { glyph: "view-refresh"; hint: L10n.tr(Qt.locale(), "Refresh"); quiet: true; onClicked: controller.refresh() }
        }
        PC.Label { text: L10n.tr(Qt.locale(), "Choose where to control playback"); color: player.secondaryInk; Layout.fillWidth: true; wrapMode: Text.WordWrap }
        QQC.ScrollView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            ColumnLayout {
                width: parent.width
                spacing: 10
                Repeater {
                    model: controller.devices
                    delegate: QQC.AbstractButton {
                        id: deviceCard
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 68
                        hoverEnabled: true
                        readonly property bool selected: modelData.id === controller.selectedId
                        onClicked: { controller.selectDevice(modelData.id); player.choosingDevice = false; }
                        background: Rectangle {
                            radius: 14
                            color: deviceCard.selected ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.12)
                                : Qt.rgba(1, 1, 1, deviceCard.hovered ? 0.09 : 0.04)
                            border.color: deviceCard.selected ? Qt.rgba(Kirigami.Theme.highlightColor.r, Kirigami.Theme.highlightColor.g, Kirigami.Theme.highlightColor.b, 0.55) : Qt.rgba(1, 1, 1, 0.09)
                        }
                        contentItem: RowLayout {
                            spacing: 10
                            Kirigami.Icon { source: deviceCard.modelData.group ? "audio-speakers-symbolic" : "audio-speakers"; Layout.preferredWidth: 22; Layout.preferredHeight: 22; color: deviceCard.selected ? Kirigami.Theme.highlightColor : player.ink }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 5
                                PC.Label { text: deviceCard.modelData.name; font.weight: Font.DemiBold; elide: Text.ElideRight; Layout.fillWidth: true }
                                PC.Label { text: !deviceCard.modelData.connected ? L10n.tr(Qt.locale(), "Offline") : deviceCard.modelData.state === "IDLE" ? L10n.tr(Qt.locale(), "Ready to play") : deviceCard.modelData.title || deviceCard.modelData.app; color: player.secondaryInk; font.pixelSize: 11; elide: Text.ElideRight; Layout.fillWidth: true }
                            }
                            Kirigami.Icon { source: "checkmark"; visible: deviceCard.selected; Layout.preferredWidth: 18; Layout.preferredHeight: 18; color: Kirigami.Theme.highlightColor }
                        }
                        padding: 12
                    }
                }
                PC.Label { visible: !controller.devices.length; text: L10n.tr(Qt.locale(), "Looking for Chromecast speakers on your network…"); wrapMode: Text.WordWrap; Layout.fillWidth: true; color: player.secondaryInk }
            }
        }
        PC.Label { text: L10n.tr(Qt.locale(), "Speaker groups are managed in Google Home."); color: player.secondaryInk; font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap }
    }

    QQC.Menu {
        id: moreMenu
        parent: moreButton
        y: moreButton.height
        QQC.Menu {
            title: L10n.tr(Qt.locale(), "Sleep timer")
            enabled: controller.available || controller.sleepRemaining > 0
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "15 minutes"); onTriggered: controller.send("sleep", 15) }
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "30 minutes"); onTriggered: controller.send("sleep", 30) }
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "45 minutes"); onTriggered: controller.send("sleep", 45) }
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "1 hour"); onTriggered: controller.send("sleep", 60) }
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "Custom timer…"); enabled: controller.available; onTriggered: sleepDialog.open() }
            QQC.MenuSeparator {}
            QQC.MenuItem { text: L10n.tr(Qt.locale(), "Cancel timer"); enabled: controller.sleepRemaining > 0; onTriggered: controller.send("sleep", 0) }
        }
        QQC.MenuSeparator {}
        QQC.MenuItem { text: "Spotify Connect…"; icon.name: Qt.resolvedUrl("../icons/spotify.svg"); onTriggered: spotifySetup.open() }
        QQC.MenuItem { text: L10n.tr(Qt.locale(), "Reconnect speakers"); icon.name: "view-refresh"; onTriggered: controller.refresh() }
        QQC.MenuSeparator {}
        QQC.MenuItem { text: L10n.tr(Qt.locale(), "Stop casting"); icon.name: "media-playback-stop"; enabled: controller.active; onTriggered: controller.send("stop") }
    }

    SpotifySetup { id: spotifySetup; parent: QQC.Overlay.overlay; controller: player.controller }
    QQC.Dialog {
        id: sleepDialog
        parent: QQC.Overlay.overlay
        anchors.centerIn: parent
        width: 302
        modal: true
        title: L10n.tr(Qt.locale(), "Sleep timer")
        footer: QQC.DialogButtonBox {
            QQC.Button { text: L10n.tr(Qt.locale(), "Start timer"); QQC.DialogButtonBox.buttonRole: QQC.DialogButtonBox.AcceptRole }
            QQC.Button { text: L10n.tr(Qt.locale(), "Cancel"); QQC.DialogButtonBox.buttonRole: QQC.DialogButtonBox.RejectRole }
        }
        onAccepted: controller.send("sleep", {minutes: customMinutes.value, fade_seconds: fade.checked && device.can_volume !== false ? fadeSeconds.value : 0})
        contentItem: ColumnLayout {
            PC.Label { text: L10n.tr(Qt.locale(), "Minutes"); Layout.fillWidth: true }
            QQC.SpinBox { id: customMinutes; from: 1; to: 1440; value: 45; editable: true; Layout.fillWidth: true }
            QQC.CheckBox {
                id: fade
                text: L10n.tr(Qt.locale(), "Fade out before pausing")
                enabled: device.can_volume !== false
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                contentItem: PC.Label {
                    text: fade.text
                    font: fade.font
                    wrapMode: Text.WordWrap
                    leftPadding: fade.indicator.width + fade.spacing
                    verticalAlignment: Text.AlignVCenter
                }
            }
            PC.Label { text: L10n.tr(Qt.locale(), "Fade duration, seconds"); visible: fade.checked; Layout.fillWidth: true }
            QQC.SpinBox { id: fadeSeconds; from: 5; to: 300; value: 30; editable: true; visible: fade.checked; Layout.fillWidth: true }
            PC.Label {
                Layout.fillWidth: true
                text: L10n.tr(Qt.locale(), "The timer survives a service restart. During computer sleep, it runs when the computer wakes.")
                wrapMode: Text.WordWrap
                font.pixelSize: 11
            }
        }
    }
}
