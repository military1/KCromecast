"""Native KDE media integration and a bounded, authenticated event stream."""
import asyncio
import hashlib
from http import HTTPStatus
import json
import logging
import secrets
import threading

from dbus_fast import BusType, DBusError, Message, MessageType, Variant
from dbus_fast.aio import MessageBus
from dbus_fast.constants import PropertyAccess
from dbus_fast.service import ServiceInterface, dbus_method, dbus_property, dbus_signal
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed

LOG = logging.getLogger("kcromecast.desktop")
READ = PropertyAccess.READ
PATH = "/org/mpris/MediaPlayer2"


def track_path(device):
    if not device.get("title"):
        return "/org/mpris/MediaPlayer2/TrackList/NoTrack"
    identity = "\0".join(str(device.get(key, "")) for key in ("id", "title", "artist", "album", "duration"))
    return "/org/kcromecast/track/t" + hashlib.sha256(identity.encode()).hexdigest()[:24]


class MediaRoot(ServiceInterface):
    def __init__(self, runtime):
        super().__init__("org.mpris.MediaPlayer2")
        self.runtime = runtime

    @dbus_method()
    def Raise(self):
        self.runtime.raise_player()

    @dbus_method()
    def Quit(self):
        raise DBusError("org.mpris.MediaPlayer2.Error.NotSupported", "The desktop service remains available.")

    @dbus_property(access=READ)
    def CanQuit(self) -> "b":
        return False

    @dbus_property(access=READ)
    def CanRaise(self) -> "b":
        return True

    @dbus_property(access=READ)
    def HasTrackList(self) -> "b":
        return False

    @dbus_property(access=READ)
    def Identity(self) -> "s":
        return "KCromecast"

    @dbus_property(access=READ)
    def DesktopEntry(self) -> "s":
        return "org.kcromecast.widget"

    @dbus_property(access=READ)
    def SupportedUriSchemes(self) -> "as":
        return []

    @dbus_property(access=READ)
    def SupportedMimeTypes(self) -> "as":
        return []


class MediaPlayer(ServiceInterface):
    def __init__(self, runtime):
        super().__init__("org.mpris.MediaPlayer2.Player")
        self.runtime = runtime
        self.previous_properties = {}
        self.previous_track = ""
        self.previous_position = 0
        self.previous_sample = 0

    @property
    def device(self):
        return self.runtime.manager.device_snapshot(self.runtime.manager.selected) or {}

    async def command(self, action, value=None):
        device = self.device
        if not device.get("connected"):
            return
        try:
            await asyncio.to_thread(self.runtime.manager.command, device["id"], action, value)
        except Exception:
            raise DBusError("org.mpris.MediaPlayer2.Error.Failed", "The receiver could not complete the command.") from None

    @dbus_method()
    async def Next(self):
        if self.CanGoNext:
            await self.command("next")

    @dbus_method()
    async def Previous(self):
        if self.CanGoPrevious:
            await self.command("previous")

    @dbus_method()
    async def Pause(self):
        if self.CanPause and self.PlaybackStatus == "Playing":
            await self.command("pause")

    @dbus_method()
    async def PlayPause(self):
        if self.CanPause or self.PlaybackStatus == "Paused":
            await self.command("toggle")

    @dbus_method()
    async def Stop(self):
        if self.CanControl:
            await self.command("stop")

    @dbus_method()
    async def Play(self):
        if self.CanPlay and self.PlaybackStatus != "Playing":
            await self.command("play")

    @dbus_method()
    async def Seek(self, Offset: "x"):
        if self.CanSeek:
            target = max(0, min(self.device.get("duration", 0), self.Position / 1_000_000 + Offset / 1_000_000))
            await self.command("seek", target)

    @dbus_method()
    async def SetPosition(self, TrackId: "o", Position: "x"):
        device = self.device
        if self.CanSeek and TrackId == track_path(device) and 0 <= Position <= device.get("duration", 0) * 1_000_000:
            await self.command("seek", Position / 1_000_000)

    @dbus_method()
    def OpenUri(self, Uri: "s"):
        raise DBusError("org.mpris.MediaPlayer2.Error.NotSupported", "Start a Cast session from your music application.")

    @dbus_signal()
    def Seeked(self, position) -> "x":
        return position

    @dbus_property(access=READ)
    def PlaybackStatus(self) -> "s":
        device = self.device
        return ("Playing" if device.get("state") in ("PLAYING", "BUFFERING") else
                "Paused" if device.get("state") == "PAUSED" else "Stopped") if device.get("connected") else "Stopped"

    @dbus_property()
    def Rate(self) -> "d":
        return 1.0

    @Rate.setter
    def Rate(self, value: "d"):
        if value != 1.0:
            raise DBusError("org.mpris.MediaPlayer2.Error.NotSupported", "Only normal playback speed is supported.")

    @dbus_property(access=READ)
    def MinimumRate(self) -> "d":
        return 1.0

    @dbus_property(access=READ)
    def MaximumRate(self) -> "d":
        return 1.0

    @dbus_property(access=READ)
    def Metadata(self) -> "a{sv}":
        device = self.device
        result = {"mpris:trackid": Variant("o", track_path(device))}
        if device.get("title"):
            result["xesam:title"] = Variant("s", device["title"])
        if device.get("artist"):
            result["xesam:artist"] = Variant("as", [device["artist"]])
        if device.get("album"):
            result["xesam:album"] = Variant("s", device["album"])
        if device.get("artwork"):
            result["mpris:artUrl"] = Variant("s", device["artwork"])
        if device.get("duration"):
            result["mpris:length"] = Variant("x", round(device["duration"] * 1_000_000))
        return result

    @dbus_property()
    def Volume(self) -> "d":
        return float(self.device.get("volume", 0)) / 100

    @Volume.setter
    async def Volume(self, value: "d"):
        if not 0 <= value <= 1:
            raise DBusError("org.freedesktop.DBus.Error.InvalidArgs", "Volume must be between zero and one.")
        if self.device.get("can_volume", True):
            await self.command("volume", round(value * 100))

    @dbus_property(access=READ)
    def Position(self) -> "x":
        return round(self.device.get("position", 0) * 1_000_000)

    @dbus_property(access=READ)
    def CanGoNext(self) -> "b":
        return self.CanControl and bool(self.device.get("can_next"))

    @dbus_property(access=READ)
    def CanGoPrevious(self) -> "b":
        return self.CanControl and bool(self.device.get("can_previous"))

    @dbus_property(access=READ)
    def CanPlay(self) -> "b":
        return self.CanControl and (self.device.get("transport") == "spotify" or self.device.get("state") in ("PLAYING", "PAUSED", "BUFFERING"))

    @dbus_property(access=READ)
    def CanPause(self) -> "b":
        return self.CanControl and bool(self.device.get("can_pause"))

    @dbus_property(access=READ)
    def CanSeek(self) -> "b":
        return self.CanControl and bool(self.device.get("can_seek"))

    @dbus_property(access=READ)
    def CanControl(self) -> "b":
        return bool(self.device.get("connected"))

    def update(self, snapshot):
        names = ("PlaybackStatus", "Metadata", "Volume", "CanGoNext", "CanGoPrevious", "CanPlay", "CanPause", "CanSeek", "CanControl")
        values = {name: getattr(self, name) for name in names}
        changed = {name: value for name, value in values.items() if value != self.previous_properties.get(name)}
        if changed:
            self.emit_properties_changed(changed)
        track, position = track_path(self.device), self.Position
        elapsed = snapshot["sampled_at"] - self.previous_sample
        expected = self.previous_position + (elapsed * 1_000_000 if self.previous_properties.get("PlaybackStatus") == "Playing" else 0)
        if track == self.previous_track and abs(position - expected) > 2_000_000:
            self.Seeked(position)
        self.previous_properties, self.previous_track = values, track
        self.previous_position, self.previous_sample = position, snapshot["sampled_at"]


class DesktopRuntime:
    def __init__(self, manager, token, port=17845):
        self.manager, self.token, self.port = manager, token, port
        self.loop = None
        self.event = None
        self.clients = {}
        self.player = None
        self.raise_pending = False
        self.ready = threading.Event()
        self.failure = None
        self.thread = threading.Thread(target=self._thread, name="desktop", daemon=True)

    def start(self):
        self.thread.start()
        if not self.ready.wait(10):
            raise RuntimeError("Desktop event server did not start")
        if self.failure:
            raise self.failure

    def notify(self):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.event.set)

    def _thread(self):
        try:
            asyncio.run(self._run())
        except Exception as error:
            self.failure = error
            self.ready.set()
            LOG.exception("Desktop integration stopped")

    async def _run(self):
        self.loop = asyncio.get_running_loop()
        self.event, self.closed = asyncio.Event(), asyncio.Event()
        session_bus = system_bus = None
        try:
            session_bus = await MessageBus().connect()
            self.player = MediaPlayer(self)
            session_bus.export(PATH, MediaRoot(self))
            session_bus.export(PATH, self.player)
            await session_bus.request_name("org.mpris.MediaPlayer2.kcromecast")
        except Exception:
            LOG.warning("MPRIS is unavailable", exc_info=True)
        try:
            system_bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
            system_bus.add_message_handler(self._system_signal)
            for rule in [
                "type='signal',sender='org.freedesktop.login1',interface='org.freedesktop.login1.Manager',member='PrepareForSleep'",
                "type='signal',sender='org.freedesktop.NetworkManager',interface='org.freedesktop.NetworkManager',member='StateChanged'",
            ]:
                await system_bus.call(Message(destination="org.freedesktop.DBus", path="/org/freedesktop/DBus",
                                              interface="org.freedesktop.DBus", member="AddMatch", signature="s", body=[rule]))
        except Exception:
            LOG.info("System network/sleep notifications unavailable")
        self.manager.subscribe(self.notify)
        try:
            async with serve(self._client, "127.0.0.1", self.port, origins=[None], compression=None,
                             max_size=4096, max_queue=4, ping_interval=30, ping_timeout=10,
                             close_timeout=2, process_request=self._check_request):
                self.ready.set()
                worker = asyncio.create_task(self._publish())
                self.event.set()
                await self.closed.wait()
                worker.cancel()
                await asyncio.gather(worker, return_exceptions=True)
        finally:
            self.manager.unsubscribe(self.notify)
            for bus in (session_bus, system_bus):
                if bus:
                    bus.disconnect()

    def _system_signal(self, message):
        if message.message_type != MessageType.SIGNAL:
            return
        wake = message.interface == "org.freedesktop.login1.Manager" and message.member == "PrepareForSleep" and message.body == [False]
        network = message.interface == "org.freedesktop.NetworkManager" and message.member == "StateChanged" and message.body and message.body[0] >= 50
        if wake or network:
            self.manager.reconnect()

    def _check_request(self, connection, request):
        if request.headers.get("Host") != f"127.0.0.1:{self.port}" or request.path != "/v1/events":
            return connection.respond(HTTPStatus.FORBIDDEN, "Forbidden\n")
        if len(self.clients) >= 8:
            return connection.respond(HTTPStatus.SERVICE_UNAVAILABLE, "Busy\n")
        return None

    async def _client(self, connection):
        try:
            raw = await asyncio.wait_for(connection.recv(), timeout=5)
            auth = json.loads(raw)
            if not isinstance(auth, dict) or not isinstance(auth.get("token"), str) or not secrets.compare_digest(auth["token"], self.token):
                await connection.close(1008, "Unauthorized")
                return
            queue = asyncio.Queue(maxsize=1)
            self.clients[connection] = queue
            await connection.send(json.dumps(self.manager.snapshot(), ensure_ascii=False, allow_nan=False))
            if self.raise_pending:
                await connection.send(json.dumps({"event": "raise"}))
                self.raise_pending = False
            # recv detects client disconnects immediately; a sender never accumulates old states.
            sender = asyncio.create_task(self._send(connection, queue))
            try:
                async for _ in connection:
                    pass
            finally:
                sender.cancel()
                await asyncio.gather(sender, return_exceptions=True)
        except (ConnectionClosed, TimeoutError, ValueError, TypeError):
            await connection.close(1008, "Invalid authentication")
        finally:
            self.clients.pop(connection, None)

    async def _send(self, connection, queue):
        try:
            while True:
                await asyncio.wait_for(connection.send(await queue.get()), timeout=5)
        except (ConnectionClosed, TimeoutError):
            await connection.close(1001, "Event stream closed")

    async def _publish(self):
        while True:
            await self.event.wait()
            await asyncio.sleep(.05)
            self.event.clear()
            snapshot = self.manager.snapshot()
            payload = json.dumps(snapshot, ensure_ascii=False, allow_nan=False)
            for queue in tuple(self.clients.values()):
                if queue.full():
                    queue.get_nowait()
                queue.put_nowait(payload)
            if self.player:
                self.player.update(snapshot)

    def raise_player(self):
        if not self.clients:
            self.raise_pending = True
            return
        payload = json.dumps({"event": "raise"})
        for queue in tuple(self.clients.values()):
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(payload)

    def stop(self):
        if self.loop and not self.loop.is_closed():
            self.loop.call_soon_threadsafe(self.closed.set)
        if self.thread.is_alive():
            self.thread.join(timeout=5)
