#!/usr/bin/env python3
"""Build the widget and a source distribution, excluding local credentials/caches."""
from pathlib import Path
import re
import zipfile
from translations import compile_translations

root = Path(__file__).resolve().parents[1]
version = re.search(r'version = "([^"]+)"', (root / "pyproject.toml").read_text())[1]
output = root / "dist"
output.mkdir(exist_ok=True)
compile_translations(root)
with zipfile.ZipFile(output / f"KCromecast-{version}.plasmoid", "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted((root / "package").rglob("*")):
        if file.is_file():
            archive.write(file, file.relative_to(root / "package"))
with zipfile.ZipFile(output / f"KCromecast-{version}-source.zip", "w", zipfile.ZIP_DEFLATED) as archive:
    for file in sorted(root.rglob("*")):
        relative = file.relative_to(root)
        if not file.is_file() or any(p in {".git", "dist", "__pycache__", "build", ".venv"} or p.endswith(".egg-info") for p in relative.parts):
            continue
        archive.write(file, Path(f"KCromecast-{version}") / relative)
print(output / f"KCromecast-{version}.plasmoid")
print(output / f"KCromecast-{version}-source.zip")
