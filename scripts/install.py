#!/usr/bin/env python3
"""Install/update KCromecast for the current user; no system packages changed."""
from pathlib import Path
import datetime
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener
from translations import compile_translations

ROOT = Path(__file__).resolve().parents[1]
HOME = Path.home()
DATA = HOME / ".local/share/kcromecast"
PLUGIN = "org.kcromecast.widget"


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    backup = DATA / ("backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S"))
    backup.mkdir(mode=0o700)
    panel_config = HOME / ".config/plasma-org.kde.plasma.desktop-appletsrc"
    if panel_config.exists():
        shutil.copy2(panel_config, backup / panel_config.name)
    installed = HOME / ".local/share/plasma/plasmoids" / PLUGIN
    if installed.exists():
        shutil.copytree(installed, backup / PLUGIN)
    (DATA / "latest-backup").write_text(str(backup) + "\n")

    python = DATA / "venv/bin/python"
    if not python.exists():
        run(sys.executable, "-m", "venv", str(DATA / "venv"))
    run(str(python), "-m", "pip", "install", "--upgrade", "-e", str(ROOT))
    run(str(python), "-m", "pip", "freeze", stdout=(DATA / "requirements.lock").open("w"))
    compile_translations(ROOT)
    run("kpackagetool6", "--type", "Plasma/Applet", "--upgrade" if installed.exists() else "--install", str(ROOT / "package"))

    config = HOME / ".config/kcromecast/service.json"
    config.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    token = json.loads(config.read_text())["token"] if config.exists() else secrets.token_urlsafe(32)
    config.write_text(json.dumps({"token": token}) + "\n")
    config.chmod(0o600)
    service = HOME / ".config/systemd/user/kcromecast.service"
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text(f'''[Unit]
Description=KCromecast — persistent Chromecast remote
After=network.target

[Service]
ExecStart="{python}" -m kcromecast
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
TimeoutStopSec=20

[Install]
WantedBy=default.target
''')
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "--now", "kcromecast.service")
    run("systemctl", "--user", "restart", "kcromecast.service")
    # Give Plasma an application identity and icon for the MPRIS player.
    desktop_entry = HOME / ".local/share/applications/org.kcromecast.widget.desktop"
    desktop_entry.parent.mkdir(parents=True, exist_ok=True)
    icon = installed / "contents/icons/kcromecast.svg"
    desktop_entry.write_text(f'''[Desktop Entry]
Type=Application
Name=KCromecast
Comment=Control your Chromecast speakers
Comment[ru]=Управление колонками Chromecast
Icon={icon}
Exec=qdbus6 org.mpris.MediaPlayer2.kcromecast /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Raise
NoDisplay=true
Categories=AudioVideo;Audio;
''')
    snapshot = None
    opener = build_opener(ProxyHandler({}))
    for _ in range(30):
        try:
            request = Request("http://127.0.0.1:17844/v1/state", headers={"Authorization": "Bearer " + token})
            with opener.open(request, timeout=2) as response:
                snapshot = json.load(response)
            if snapshot["devices"]:
                break
        except (OSError, ValueError):
            pass
        time.sleep(.3)
    if snapshot is None:
        raise SystemExit("The service did not start. Existing panel widgets were not replaced.")
    devices = snapshot["devices"]
    selected = next((d["id"] for d in devices if d["group"] and d["state"] != "IDLE"), "")
    if not selected:
        selected = next((d["id"] for d in devices if d["group"]), "")
    script = '''
var replacement = null;
var previous = [];
var destination = null;
var position = 3;
for (var panel of panels()) {
    for (var widget of panel.widgets()) {
        if (widget.type === "org.kcromecast.widget") replacement = widget;
        if (widget.type === "de.agundur.kcast") {
            previous.push(widget); destination = panel; position = widget.index;
        }
    }
}
if (!replacement) {
    if (!destination) destination = panels()[0];
    if (!destination) throw new Error("No panel found");
    replacement = destination.addWidget("org.kcromecast.widget");
    replacement.index = position;
}
replacement.currentConfigGroup = ["General"];
replacement.writeConfig("backendToken", TOKEN);
if (!replacement.readConfig("preferredDevice", "")) replacement.writeConfig("preferredDevice", DEVICE);
replacement.currentConfigGroup = [];
replacement.writeConfig("popupWidth", 352);
replacement.writeConfig("popupHeight", 392);
for (var widget of previous) widget.remove();
print("KCromecast widget " + replacement.id);
'''.replace("TOKEN", json.dumps(token)).replace("DEVICE", json.dumps(selected))
    result = subprocess.run(["qdbus6", "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script],
                            capture_output=True, text=True)
    if result.returncode:
        raise SystemExit("Could not update the panel. The companion service is installed; panel backup: " + str(backup))
    print(result.stdout.strip())
    # Prevent other users on this computer from reading the per-user API token.
    panel_config.chmod(0o600)
    print("Installed KCromecast. Backup:", backup)


if __name__ == "__main__":
    main()
