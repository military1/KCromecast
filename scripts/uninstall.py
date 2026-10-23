#!/usr/bin/env python3
"""Remove KCromecast for the current user. Keep settings unless --purge is given."""
import argparse
from pathlib import Path
import shutil
import subprocess

try:
    from .install import PLUGIN, find_qdbus, restart_panel, xdg
except ImportError:
    from install import PLUGIN, find_qdbus, restart_panel, xdg


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--purge", action="store_true", help="Also remove KCromecast settings, tokens, backups and artwork")
    parser.add_argument("--no-restart", action="store_true")
    args = parser.parse_args()
    import os
    if os.geteuid() == 0:
        raise SystemExit("Run as your desktop user, without sudo.")
    data_home, config_home = xdg("XDG_DATA_HOME", ".local/share"), xdg("XDG_CONFIG_HOME", ".config")
    subprocess.run(["systemctl", "--user", "disable", "--now", "kcromecast.service"], check=False, capture_output=True)
    qdbus = find_qdbus()
    if qdbus:
        script = '''for (var container of panels().concat(desktops())) {
    for (var widget of container.widgets()) if (widget.type === "org.kcromecast.widget") widget.remove();
}'''
        subprocess.run([qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", script], check=False, capture_output=True, timeout=15)
    shutil.rmtree(data_home / "plasma/plasmoids" / PLUGIN, ignore_errors=True)
    shutil.rmtree(data_home / "kcromecast/venv", ignore_errors=True)
    (config_home / "systemd/user/kcromecast.service").unlink(missing_ok=True)
    (data_home / "applications/org.kcromecast.widget.desktop").unlink(missing_ok=True)
    subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
    if args.purge:
        for path in (data_home / "kcromecast", config_home / "kcromecast", xdg("XDG_CACHE_HOME", ".cache") / "kcromecast"):
            shutil.rmtree(path, ignore_errors=True)
    if not args.no_restart:
        restart_panel()
    print("KCromecast removed." + (" Settings removed." if args.purge else " Settings and backups kept."))


if __name__ == "__main__":
    main()
