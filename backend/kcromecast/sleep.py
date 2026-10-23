"""A persistent wall-clock sleep timer; no periodic wakeups while inactive."""
import logging
import math
import threading
import time

from .storage import read_json, write_json

LOG = logging.getLogger("kcromecast.sleep")


class SleepTimer:
    def __init__(self, path, get_state, command, changed):
        self.path, self.get_state, self.command, self.changed = path, get_state, command, changed
        self.condition = threading.Condition(threading.RLock())
        self.closed = False
        self.generation = 0
        self.data = read_json(path)
        try:
            valid = (isinstance(self.data.get("device"), str) and bool(self.data["device"])
                     and math.isfinite(float(self.data.get("deadline", 0)))
                     and 0 < float(self.data.get("minutes", 0)) <= 1440
                     and 0 <= int(self.data.get("fade_seconds", 0)) <= 300)
        except (TypeError, ValueError):
            valid = False
        if not valid:
            self.data = {}
        self.state_lock = threading.Lock()
        self.public_data = dict(self.data)
        self.thread = threading.Thread(target=self._run, name="sleep-timer", daemon=True)

    def start(self):
        self.thread.start()

    def snapshot(self):
        # Network commands during a fade must never block the UI/event loop.
        with self.state_lock:
            data = self.public_data
            return {"device": data.get("device", ""), "minutes": data.get("minutes", 0),
                    "deadline": data.get("deadline", 0),
                    "remaining": max(0, math.ceil(data.get("deadline", 0) - time.time())),
                    "fade_seconds": data.get("fade_seconds", 0),
                    "fading": "original_volume" in data}

    def set(self, device, minutes, fade_seconds=0):
        try:
            minutes, fade_seconds = float(minutes), int(fade_seconds)
        except (ValueError, TypeError):
            raise ValueError("Invalid sleep timer") from None
        if not math.isfinite(minutes) or not 0 <= minutes <= 1440 or not 0 <= fade_seconds <= 300:
            raise ValueError("Invalid sleep timer")
        self.cancel(restore=True)
        if minutes:
            with self.condition:
                self.data = {"device": device, "deadline": time.time() + minutes * 60,
                             "minutes": minutes, "fade_seconds": min(fade_seconds, int(minutes * 60))}
                self.generation += 1
                self._save()
                self.condition.notify_all()
            self.changed()

    def _save(self):
        write_json(self.path, self.data)
        with self.state_lock:
            self.public_data = dict(self.data)

    def _restore(self, data):
        if "original_volume" not in data:
            return
        state = self.get_state(data["device"])
        # A volume changed by the phone must never be overwritten by the timer.
        if state and state.get("connected") and abs(state.get("volume", -100) - data.get("last_volume", -200)) <= 1:
            try:
                self.command(data["device"], "volume", data["original_volume"])
            except Exception:
                LOG.debug("Could not restore sleep volume", exc_info=True)

    def cancel(self, restore=True):
        # Serialize cancellation with a fade step; no late command may follow it.
        with self.condition:
            old, self.data = self.data, {}
            self.generation += 1
            self._save()
            if restore:
                self._restore(old)
            self.condition.notify_all()
        self.changed()

    def user_volume(self, device):
        with self.condition:
            fading = self.data.get("device") == device and "original_volume" in self.data
        if fading:
            self.cancel(restore=False)

    def wake(self):
        with self.condition:
            self.condition.notify_all()

    def _step(self):
        """Run with the condition held. Returns delay until the next useful work."""
        if not self.data:
            return None
        data = self.data
        remaining = data["deadline"] - time.time()
        fade = data.get("fade_seconds", 0)
        if remaining > fade:
            return remaining - fade
        state = self.get_state(data["device"])
        if not state or not state.get("connected"):
            if remaining < -120:
                self.data = {}
                self._save()
                self.changed("The sleep timer ended, but the speakers did not respond.")
                return None
            return 3
        if remaining <= 0 or state.get("state") not in ("PLAYING", "BUFFERING"):
            if state.get("state") in ("PLAYING", "BUFFERING"):
                self.command(data["device"], "pause", None)
            self._restore(data)
            self.data = {}
            self._save()
            self.changed()
            return None
        volume = state.get("volume", 0)
        if "original_volume" not in data:
            data["original_volume"] = volume
            data["last_volume"] = volume
            self._save()
            self.changed()
        elif abs(volume - data["last_volume"]) > 1:
            # An external volume change during fading cancels the timer.
            self.data = {}
            self._save()
            self.changed()
            return None
        level = max(0, round(data["original_volume"] * remaining / max(1, fade)))
        if level != data["last_volume"]:
            self.command(data["device"], "volume", level)
            data["last_volume"] = level
            self._save()
        # Spotify is a cloud API; avoid per-second volume writes/rate limits.
        return min(5 if data["device"].startswith("spotify:") else 1, remaining)

    def _run(self):
        with self.condition:
            while not self.closed:
                try:
                    delay = self._step()
                except Exception:
                    LOG.debug("Sleep action failed; retrying", exc_info=True)
                    delay = 3
                if not self.closed:
                    self.condition.wait(delay)

    def stop(self):
        with self.condition:
            self.closed = True
            self.condition.notify_all()
        if self.thread.is_alive():
            self.thread.join(timeout=8)
