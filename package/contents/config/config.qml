import "../ui/Locale.js" as L10n
import org.kde.plasma.configuration

ConfigModel {
    ConfigCategory {
        name: L10n.tr(Qt.locale(), "Appearance")
        icon: "preferences-desktop-theme-global"
        source: "configAppearance.qml"
    }
}
