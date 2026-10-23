#!/usr/bin/env python3
"""Install KCromecast and its companion service for the current Plasma user."""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import time
from urllib.request import Request, ProxyHandler, build_opener

try:
    from .translations import compile_translations
except ImportError:
    from translations import compile_translations

ROOT = Path(__file__).resolve().parents[1]
PLUGIN = "org.kcromecast.widget"


def xdg(variable, fallback):
    value = os.environ.get(variable, "")
    return Path(value) if value and Path(value).is_absolute() else Path.home() / fallback


def find_qdbus():
    candidates = [shutil.which("qdbus6"), shutil.which("qdbus-qt6"),
                  "/usr/lib/qt6/bin/qdbus", "/usr/lib64/qt6/bin/qdbus",
                  "/usr/lib/x86_64-linux-gnu/qt6/bin/qdbus"]
    return next((str(path) for path in candidates if path and Path(path).is_file() and os.access(path, os.X_OK)), None)


def plasma_version(output):
    match = re.search(r"\b(\d+)\.(\d+)(?:\.(\d+))?", output)
    return tuple(int(value or 0) for value in match.groups()) if match else None


def qml_roots():
    roots = [Path(value) for value in os.environ.get("QML_IMPORT_PATH", "").split(":") if value]
    roots.extend((Path("/usr/lib/qt6/qml"), Path("/usr/lib64/qt6/qml")))
    roots.extend(Path("/usr/lib").glob("*-linux-gnu/qt6/qml"))
    return roots


def preflight():
    if os.geteuid() == 0:
        raise RuntimeError("Run the installer as your desktop user, without sudo.")
    if sys.version_info < (3, 11):
        raise RuntimeError("Python 3.11 or newer is required.")
    missing = [name for name in ("plasmashell", "kpackagetool6", "msgfmt", "systemctl") if not shutil.which(name)]
    qdbus = find_qdbus()
    if not qdbus:
        missing.append("Qt 6 qdbus")
    for module in ("QtWebSockets", "QtQuick/Effects"):
        if not any((root / module / "qmldir").is_file() for root in qml_roots()):
            missing.append(module + " QML module")
    if missing:
        raise RuntimeError("Missing dependencies: " + ", ".join(missing) + ". Run ./install.sh to install them.")
    result = subprocess.run(["plasmashell", "--version"], capture_output=True, text=True, timeout=10)
    version = plasma_version(result.stdout + result.stderr)
    if result.returncode or not version or version < (6, 0, 0) or version >= (7, 0, 0):
        raise RuntimeError("KCromecast requires KDE Plasma 6.0 or newer in the Plasma 6 series.")
    result = subprocess.run([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.freedesktop.DBus.Peer.Ping"], capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("Start the installer from a terminal in your running KDE Plasma session.")
    return qdbus, version


def run(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def atomic_config(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    temporary = path.with_name(path.name + ".new")
    descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w") as stream:
            json.dump(data, stream)
            stream.write("\n")
        temporary.chmod(0o600)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def service_text(python, config):
    def quoted(path):
        return '"' + str(path).replace("%", "%%").replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f'''[Unit]
Description=KCromecast companion service
After=network.target

[Service]
ExecStart={quoted(python)} -m kcromecast --config {quoted(config)}
Restart=on-failure
RestartSec=3
UMask=0077
NoNewPrivileges=true
PrivateTmp=true
TimeoutStopSec=20

[Install]
WantedBy=default.target
'''


def panel_script(token, selected):
    # Inject values as JS literals once. Replacing placeholder text afterwards
    # could modify a user value that happens to contain another placeholder.
    return '''
var replacements = [];
for (var container of panels().concat(desktops())) {
    for (var widget of container.widgets()) {
        if (widget.type === "org.kcromecast.widget") replacements.push(widget);
    }
}
if (!replacements.length && panels().length) {
    replacements.push(panels()[0].addWidget("org.kcromecast.widget"));
}
for (var widget of replacements) {
    widget.currentConfigGroup = ["General"];
    widget.writeConfig("backendToken", %s);
    if (!widget.readConfig("preferredDevice", "")) widget.writeConfig("preferredDevice", %s);
    widget.currentConfigGroup = [];
    widget.writeConfig("popupWidth", 352);
    widget.writeConfig("popupHeight", 392);
}
print("Configured KCromecast widgets: " + replacements.length);
''' % (json.dumps(token), json.dumps(selected))


def wait_for_service(token, timeout=15):
    opener = build_opener(ProxyHandler({}))
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            request = Request("http://127.0.0.1:17844/v1/state", headers={"Authorization": "Bearer " + token})
            with opener.open(request, timeout=2) as response:
                return json.load(response)
        except (OSError, ValueError):
            time.sleep(.2)
    raise RuntimeError("The service did not start. Run: journalctl --user -u kcromecast.service -n 50")


def restart_panel():
    result = subprocess.run(["systemctl", "--user", "show", "plasma-plasmashell.service", "-p", "LoadState", "--value"], capture_output=True, text=True)
    print("Reloading Plasma panels (your applications stay open).", flush=True)
    if result.returncode == 0 and result.stdout.strip() == "loaded":
        run("systemctl", "--user", "restart", "plasma-plasmashell.service")
    else:
        subprocess.Popen(["plasmashell", "--replace"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL, start_new_session=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check prerequisites without changing anything")
    parser.add_argument("--no-restart", action="store_true", help="Leave Plasma running; log out/in to load updated QML")
    parser.add_argument("--no-panel", action="store_true", help="Install the package and service; add the widget manually")
    args = parser.parse_args(argv)
    qdbus, version = preflight()
    print("KDE Plasma " + ".".join(map(str, version)), flush=True)
    if args.check:
        print("Prerequisites OK.")
        return

    data_home, config_home = xdg("XDG_DATA_HOME", ".local/share"), xdg("XDG_CONFIG_HOME", ".config")
    data, config_dir = data_home / "kcromecast", config_home / "kcromecast"
    installed = data_home / "plasma/plasmoids" / PLUGIN
    panel_config = config_home / "plasma-org.kde.plasma.desktop-appletsrc"
    service = config_home / "systemd/user/kcromecast.service"
    desktop_entry = data_home / "applications/org.kcromecast.widget.desktop"
    data.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = data / ("backup-" + datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f"))
    backup.mkdir(mode=0o700)
    for path in (panel_config, service, desktop_entry):
        if path.exists():
            shutil.copy2(path, backup / path.name)
    if installed.exists():
        shutil.copytree(installed, backup / PLUGIN)
    (data / "latest-backup").write_text(str(backup) + "\n")

    python = data / "venv/bin/python"
    if (data / "venv").exists():
        broken = not python.exists()
        if not broken:
            probe = subprocess.run([str(python), "-m", "pip", "--version"], capture_output=True)
            broken = probe.returncode != 0
        if broken:
            shutil.move(str(data / "venv"), str(backup / "venv"))
    if not python.exists():
        run(sys.executable, "-m", "venv", str(data / "venv"))
    # Copy the package into the venv: downloaded sources may be deleted afterwards.
    print("Installing KCromecast and Python dependencies...", flush=True)
    run(str(python), "-m", "pip", "install", "--quiet", "--upgrade", str(ROOT))
    run(str(python), "-m", "pip", "check")
    with (data / "requirements.lock").open("w") as stream:
        run(str(python), "-m", "pip", "freeze", stdout=stream)

    config = config_dir / "service.json"
    if config.exists():
        shutil.copy2(config, backup / "service.json")
    try:
        existing = json.loads(config.read_text()) if config.exists() else {}
    except (OSError, ValueError):
        existing = {}
    if not isinstance(existing, dict):
        existing = {}
    token = existing.get("token")
    if not isinstance(token, str) or len(token) < 16 or not token.isascii():
        token = secrets.token_urlsafe(32)
    atomic_config(config, {**existing, "token": token})
    compile_translations(ROOT)
    run("kpackagetool6", "--type", "Plasma/Applet", "--upgrade" if installed.exists() else "--install", str(ROOT / "package"))
    service.parent.mkdir(parents=True, exist_ok=True)
    service.write_text(service_text(python, config))
    run("systemctl", "--user", "daemon-reload")
    run("systemctl", "--user", "enable", "kcromecast.service")
    run("systemctl", "--user", "restart", "kcromecast.service")
    snapshot = wait_for_service(token)

    desktop_entry.parent.mkdir(parents=True, exist_ok=True)
    desktop_entry.write_text(f'''[Desktop Entry]
Type=Application
Name=KCromecast
Comment=Chromecast remote for KDE Plasma
Comment[ru]=Пульт Chromecast для KDE Plasma
Icon={installed}/contents/icons/kcromecast.svg
Exec={qdbus} org.mpris.MediaPlayer2.kcromecast /org/mpris/MediaPlayer2 org.mpris.MediaPlayer2.Raise
NoDisplay=true
Categories=AudioVideo;Audio;
''')
    shutil.copytree(ROOT / "scripts", data / "scripts", dirs_exist_ok=True,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    shutil.copy2(ROOT / "uninstall.sh", data / "uninstall.sh")
    if not args.no_panel:
        selected = snapshot.get("selected", "")
        result = subprocess.run([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", panel_script(token, selected)], capture_output=True, text=True, timeout=20)
        if result.returncode:
            raise RuntimeError("Installed the service and widget, but could not configure the panel. Backup: " + str(backup))
        print(result.stdout.strip())
        if panel_config.exists():
            panel_config.chmod(0o600)
        if not args.no_restart:
            restart_panel()
    print("KCromecast installed. Backups: " + str(backup))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        raise SystemExit("Installation failed: " + str(error))
