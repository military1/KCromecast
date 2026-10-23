from pathlib import Path
import shutil
import subprocess
import sys
import unittest


class DesktopIntegrationTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("dbus-run-session"), "dbus-run-session is not installed")
    def test_isolated_mpris_and_event_stream(self):
        result = subprocess.run(["dbus-run-session", "--", sys.executable,
                                 str(Path(__file__).with_name("desktop_probe.py")), "-v"],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
