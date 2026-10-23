#!/usr/bin/env python3
"""Build release archives from an explicit list of project directories."""
import hashlib
from pathlib import Path
import tomllib
import zipfile

try:
    from .translations import compile_translations
except ImportError:
    from translations import compile_translations

ROOT = Path(__file__).resolve().parents[1]
SOURCE_FILES = ("README.md", "README.ru.md", "LICENSE", "CHANGELOG.md", "pyproject.toml",
                "requirements.lock", "install.sh", "uninstall.sh", ".gitignore")
SOURCE_DIRS = ("backend", "package", "translations", "scripts", "tests", "docs", ".github")


def source_files(root):
    for name in SOURCE_FILES:
        path = root / name
        if path.is_file():
            yield path
    for name in SOURCE_DIRS:
        for path in sorted((root / name).rglob("*")):
            if (path.is_file() and not path.is_symlink() and "__pycache__" not in path.parts
                    and path.suffix != ".pyc" and not any(part.endswith(".egg-info") for part in path.parts)):
                yield path


def main():
    version = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    import json
    metadata = json.loads((ROOT / "package/metadata.json").read_text())
    if metadata["KPlugin"]["Version"] != version:
        raise SystemExit("Widget and Python package versions do not match")
    output = ROOT / "dist"
    output.mkdir(exist_ok=True)
    compile_translations(ROOT)
    package = output / f"KCromecast-{version}.plasmoid"
    source = output / f"KCromecast-{version}-source.zip"
    with zipfile.ZipFile(package, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted((ROOT / "package").rglob("*")):
            if path.is_file() and not path.is_symlink():
                archive.write(path, path.relative_to(ROOT / "package"))
    with zipfile.ZipFile(source, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in source_files(ROOT):
            archive.write(path, Path(f"KCromecast-{version}") / path.relative_to(ROOT))
    checksums = "".join(hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in (package, source))
    (output / "SHA256SUMS").write_text(checksums)
    for path in (package, source, output / "SHA256SUMS"):
        print(path)


if __name__ == "__main__":
    main()
