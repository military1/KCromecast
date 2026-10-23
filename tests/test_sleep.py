import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock

from kcromecast.sleep import SleepTimer
from kcromecast.storage import write_json


class SleepTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "sleep.json"
        self.state = {"connected": True, "state": "PLAYING", "volume": 60}
        self.commands = []
        self.changed = Mock()
        self.timer = self.make_timer()

    def make_timer(self):
        def command(device, action, value):
            self.commands.append((device, action, value))
            if action == "volume":
                self.state["volume"] = value
            elif action == "pause":
                self.state["state"] = "PAUSED"
        timer = SleepTimer(self.path, lambda device: self.state, command, self.changed)
        self.addCleanup(timer.stop)
        return timer

    def step(self):
        with self.timer.condition:
            return self.timer._step()

    def test_custom_minutes_and_deadline_survive_restart(self):
        self.timer.set("group", 37, 45)
        restored = self.make_timer()
        self.assertEqual(restored.snapshot()["minutes"], 37)
        self.assertEqual(restored.snapshot()["fade_seconds"], 45)
        self.assertEqual(restored.snapshot()["deadline"], self.timer.snapshot()["deadline"])
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_inactive_timer_has_no_periodic_wakeup(self):
        self.assertIsNone(self.step())
        self.assertFalse(self.commands)

    def test_ui_snapshot_does_not_wait_for_a_slow_timer_command(self):
        entered, release = threading.Event(), threading.Event()
        def slow_action():
            with self.timer.condition:
                entered.set()
                release.wait(2)
        worker = threading.Thread(target=slow_action)
        worker.start()
        self.assertTrue(entered.wait(1))
        try:
            start = time.monotonic()
            self.timer.snapshot()
            self.assertLess(time.monotonic() - start, .1)
        finally:
            release.set()
            worker.join()

    def test_fade_pauses_once_then_restores_original_volume(self):
        self.timer.set("group", 1, 30)
        self.timer.data["deadline"] = time.time() + 15
        self.step()
        self.assertAlmostEqual(self.state["volume"], 30, delta=1)
        self.timer.data["deadline"] = time.time() - 1
        self.step()
        self.step()
        self.assertEqual(self.commands[-2:], [("group", "pause", None), ("group", "volume", 60)])
        self.assertEqual(self.timer.snapshot()["device"], "")
        self.assertEqual(json.loads(self.path.read_text()), {})

    def test_cancel_during_fade_restores_volume_and_prevents_late_pause(self):
        self.timer.set("group", 1, 30)
        self.timer.data["deadline"] = time.time() + 15
        self.step()
        self.timer.cancel()
        self.step()
        self.assertEqual(self.state["volume"], 60)
        self.assertFalse(any(action == "pause" for _, action, _ in self.commands))

    def test_external_volume_change_is_not_overwritten(self):
        self.timer.set("group", 1, 30)
        self.timer.data["deadline"] = time.time() + 15
        self.step()
        self.state["volume"] = 44
        self.step()
        self.assertEqual(self.state["volume"], 44)
        self.assertEqual(self.timer.snapshot()["device"], "")

    def test_expired_restored_timer_waits_for_reconnection(self):
        write_json(self.path, {"device": "group", "deadline": time.time() - 5, "minutes": 12, "fade_seconds": 0})
        self.timer = self.make_timer()
        self.state["connected"] = False
        self.assertEqual(self.step(), 3)
        self.assertFalse(self.commands)
        self.state["connected"] = True
        self.step()
        self.assertEqual(self.commands, [("group", "pause", None)])

    def test_very_old_deadline_does_not_pause_a_later_session(self):
        self.timer.data = {"device": "group", "deadline": time.time() - 1000, "minutes": 1, "fade_seconds": 0}
        self.state["connected"] = False
        self.step()
        self.assertEqual(self.timer.snapshot()["device"], "")
        self.assertFalse(self.commands)

    def test_invalid_and_nonfinite_values_do_not_set_timer(self):
        for value in [-1, 1441, float("nan"), float("inf"), "invalid"]:
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.timer.set("group", value)

