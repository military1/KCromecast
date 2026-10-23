"""Keep both languages complete, including receiver errors and settings."""
import gettext
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class TranslationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("qml6"), "Qt 6 QML runtime is not installed")
    def test_system_ui_language_with_real_qt_locales(self):
        module = ROOT / "package/contents/ui/Locale.js"
        source = f'''import QtQuick
import "{module}" as L10n
Item {{
    Component.onCompleted: {{
        console.log("KCLOCALE", JSON.stringify({{language: L10n.languageFor(Qt.locale()),
            text: L10n.tr(Qt.locale(), "Choose speakers")}}));
        Qt.quit();
    }}
}}
'''
        cases = [
            ("ru_RU.UTF-8", "ru:en", "ru"),
            ("en_US.UTF-8", "en:ru", "en"),
            ("ro_MD.UTF-8", "ro:ru", "en"),
            ("de_DE.UTF-8", "de:ru", "en"),
            ("C.UTF-8", "", "en"),
        ]
        with tempfile.TemporaryDirectory(prefix="kcromecast-locale-") as directory:
            probe = Path(directory) / "probe.qml"
            probe.write_text(source)
            for locale, languages, expected in cases:
                with self.subTest(locale=locale, languages=languages):
                    env = {key: value for key, value in os.environ.items() if not key.startswith("LC_")}
                    env.update(LANG=locale, LANGUAGE=languages, LC_NUMERIC="ru_RU.UTF-8",
                               QT_QPA_PLATFORM="offscreen", QT_FORCE_STDERR_LOGGING="1")
                    result = subprocess.run([shutil.which("qml6"), str(probe)], env=env,
                                            capture_output=True, text=True, timeout=15)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    match = re.search(r"KCLOCALE (\{[^\n]+\})", result.stderr)
                    self.assertIsNotNone(match, result.stderr)
                    data = json.loads(match[1])
                    self.assertEqual(data["language"], expected)
                    self.assertEqual(data["text"], "Выбрать колонки" if expected == "ru" else "Choose speakers")

    def test_catalogs_cover_the_interface_and_receiver_errors(self):
        catalogs = {}
        for language in ("en", "ru"):
            path = ROOT / f"package/contents/locale/{language}/LC_MESSAGES/plasma_applet_org.kcromecast.widget.mo"
            with path.open("rb") as stream:
                catalogs[language] = gettext.GNUTranslations(stream)
        messages = set()
        for path in (ROOT / "package/contents").rglob("*.qml"):
            messages.update(re.findall(r'L10n.tr\(Qt.locale\(\), "([^"]+)"', path.read_text()))
        service = "\n".join((ROOT / "backend/kcromecast" / name).read_text() for name in ("service.py", "sleep.py", "spotify.py"))
        messages.update(re.findall(r'raise ValueError\("([^"]+)"\)', service))
        messages.update(re.findall(r'self.error = "([^"]+)"', service))
        messages.update(re.findall(r'\{"error": "([^"]+)"\}', service))
        for message in sorted(messages):
            with self.subTest(message=message):
                self.assertEqual(catalogs["en"].gettext(message), message)
                self.assertNotEqual(catalogs["ru"].gettext(message), message)


if __name__ == "__main__":
    unittest.main()
