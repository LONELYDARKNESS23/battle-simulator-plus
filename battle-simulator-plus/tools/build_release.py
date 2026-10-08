"""Build a portable source ZIP from an explicit public-file allowlist."""

import argparse
import hashlib
import json
import re
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = {
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    "README.md",
    "start.py",
    "launcher.py",
    "Launch.ps1",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "START_GAME.bat",
    "START_GAME.sh",
    "config.example.json",
    "package.json",
    "pyproject.toml",
    "requirements-dev.txt",
    ".prettierrc.json",
}
SOURCE_DIRS = {"game", "web", "tests", "tools", "docs", ".github"}
EXTENSIONS = {".py", ".js", ".mjs", ".html", ".css", ".svg", ".md", ".yml", ".jpg", ".png"}


def public_files(root=ROOT):
    root = Path(root).resolve()
    files = [root / name for name in ROOT_FILES if (root / name).is_file()]
    for directory in SOURCE_DIRS:
        files.extend(
            path
            for path in (root / directory).rglob("*")
            if path.is_file() and path.suffix in EXTENSIONS and "__pycache__" not in path.parts
        )
    for path in files:
        if path.is_symlink() or not path.resolve().is_relative_to(root):
            raise ValueError("Release files must belong to this project")
    return sorted(files, key=lambda p: p.relative_to(root).as_posix())


def build_release(output=None, root=ROOT):
    root = Path(root).resolve()
    version = json.loads((root / "package.json").read_text(encoding="utf-8"))["version"]
    if not isinstance(version, str) or not re.fullmatch(
        r"\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?", version
    ):
        raise ValueError("Release version must be a semantic version, without path separators")
    folder = f"rift-battle-simulator-{version}"
    output = Path(output) if output else root / "dist" / f"{folder}.zip"
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in public_files(root):
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"{folder}/{relative}", (2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (0o100755 if relative.endswith(".sh") else 0o100644) << 16
            data = path.read_bytes()
            if relative.endswith(".bat"):
                data = data.replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
            archive.writestr(info, data)
    digest = hashlib.sha256(output.read_bytes()).hexdigest()
    output.with_suffix(".zip.sha256").write_text(f"{digest}  {output.name}\n", encoding="ascii")
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    print(build_release(args.output))
