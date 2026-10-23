import QtQuick
import QtQuick.Controls as QQC
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PC
import "Locale.js" as L10n

QQC.Dialog {
    id: setup
    required property var controller
    property bool working: false
    property string message: ""
    title: "Spotify Connect"
    modal: true
    width: 324
    anchors.centerIn: parent
    footer: QQC.DialogButtonBox {
        QQC.Button {
            text: L10n.tr(Qt.locale(), "Close")
            QQC.DialogButtonBox.buttonRole: QQC.DialogButtonBox.RejectRole
        }
    }
    onOpened: { clientId.text = controller.spotify.client_id || ""; message = ""; }

    contentItem: ColumnLayout {
        spacing: 10
        PC.Label {
            Layout.fillWidth: true
            text: setup.controller.spotify.connected ? L10n.tr(Qt.locale(), "Spotify account connected")
                : L10n.tr(Qt.locale(), "Connect Spotify to control your Spotify Connect devices. Spotify Premium is required.")
            wrapMode: Text.WordWrap
        }
        QQC.TextField {
            id: clientId
            Layout.fillWidth: true
            placeholderText: "Spotify Client ID"
            enabled: !setup.working && !setup.controller.spotify.connected
            selectByMouse: true
            maximumLength: 32
            Accessible.name: "Spotify Client ID"
        }
        PC.Label {
            Layout.fillWidth: true
            text: L10n.tr(Qt.locale(), "Register this redirect URI in your Spotify app:")
            wrapMode: Text.WordWrap
            font.pixelSize: 11
        }
        SelectableText {
            text: setup.controller.spotify.redirect_uri || "http://127.0.0.1:17844/spotify/callback"
            font.pixelSize: 11
            maximumLines: 2
        }
        QQC.Button {
            text: L10n.tr(Qt.locale(), "Open Spotify Developer Dashboard")
            Layout.fillWidth: true
            onClicked: Qt.openUrlExternally("https://developer.spotify.com/dashboard")
        }
        QQC.Button {
            Layout.fillWidth: true
            text: setup.controller.spotify.connected ? L10n.tr(Qt.locale(), "Disconnect account") : L10n.tr(Qt.locale(), "Sign in with Spotify")
            enabled: !setup.working && (setup.controller.spotify.connected || clientId.text.length === 32)
            onClicked: {
                setup.working = true;
                setup.message = "";
                if (setup.controller.spotify.connected) {
                    setup.controller.request("POST", "spotify/disconnect", {}, function(status, response) {
                        setup.working = false;
                        if (status !== 200) setup.message = L10n.tr(Qt.locale(), response.error || "Spotify did not respond. Try again.");
                    });
                } else {
                    setup.controller.request("POST", "spotify/authorize", {client_id: clientId.text.trim(), language: L10n.languageFor(Qt.locale())}, function(status, response) {
                        setup.working = false;
                        if (status === 200 && response.authorization_url) {
                            Qt.openUrlExternally(response.authorization_url);
                            setup.message = L10n.tr(Qt.locale(), "Complete sign-in in your browser, then return here.");
                        } else setup.message = L10n.tr(Qt.locale(), response.error || "Spotify did not respond. Try again.");
                    });
                }
            }
        }
        PC.Label {
            visible: text.length > 0
            text: setup.message || L10n.tr(Qt.locale(), setup.controller.spotify.error || "")
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: 11
        }
    }
}
