import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from scripts.build import source_files
from scripts.install import PLUGIN, atomic_config, find_qdbus, install_icon, panel_script, plasma_version, service_text


class InstallerTests(unittest.TestCase):
    def test_icon_is_installed_under_the_metadata_theme_name(self):
        with tempfile.TemporaryDirectory() as directory:
            path = install_icon(Path(directory))
            self.assertEqual(path.name, PLUGIN + ".svg")
            self.assertIn("<svg", path.read_text())

    def test_plasma_version_parser(self):
        self.assertEqual(plasma_version("plasmashell 6.0.0"), (6, 0, 0))
        self.assertEqual(plasma_version("plasmashell 6.8.1"), (6, 8, 1))
        self.assertEqual(plasma_version("plasmashell 5.27.12"), (5, 27, 12))
        self.assertIsNone(plasma_version("not installed"))

    def test_panel_values_are_escaped_without_substituting_inside_them(self):
        token = 'TOKEN-DEVICE-"quoted"-\\test'
        script = panel_script(token, "speaker")
        self.assertIn(json.dumps(token), script)
        self.assertIn(json.dumps("speaker"), script)
        self.assertNotIn("widget.remove()", script)

    def test_systemd_paths_escape_spaces_percent_and_quotes(self):
        text = service_text(Path('/home/user name/100%/venv/bin/python'), Path('/home/user name/config.json'))
        self.assertIn('ExecStart="/home/user name/100%%/venv/bin/python"', text)
        self.assertIn('--config "/home/user name/config.json"', text)

    def test_new_token_file_is_private(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "config/service.json"
            atomic_config(path, {"token": "private"})
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(json.loads(path.read_text()), {"token": "private"})
            self.assertFalse(path.with_name("service.json.new").exists())

    def test_source_allowlist_excludes_local_credentials_and_build_output(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for name in ["README.md", ".env", "private.json", "dist/archive.zip", ".git/config", "docs/usage.md", "translations/en.po", "translations/ru.po", "backend/__pycache__/cache.pyc"]:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("test")
            names = {str(path.relative_to(root)) for path in source_files(root)}
            self.assertEqual(names, {"README.md", "docs/usage.md", "translations/en.po", "translations/ru.po"})

    @patch("scripts.install.shutil.which", return_value=None)
    @patch("scripts.install.os.access", return_value=True)
    @patch("scripts.install.Path.is_file")
    def test_debian_qdbus_location_is_accepted(self, is_file, access, which):
        is_file.side_effect = lambda: True
        self.assertEqual(find_qdbus(), "/usr/lib/qt6/bin/qdbus")
