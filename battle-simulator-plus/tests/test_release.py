import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from tools.build_release import build_release


class ReleaseTests(unittest.TestCase):
    def test_real_release_contains_complete_game_and_excludes_local_state(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = build_release(Path(temporary) / "source.zip")
            with zipfile.ZipFile(result) as archive:
                names = {"/".join(name.split("/")[1:]) for name in archive.namelist()}
                required = {
                    "start.py",
                    "launcher.py",
                    "Launch.ps1",
                    "START_GAME.bat",
                    "START_GAME.sh",
                    "game/engine.py",
                    "game/commanders.py",
                    "game/storage.py",
                    "web/index.html",
                    "web/app.js",
                    "web/client-state.js",
                    "web/battlefield-art.js",
                    "web/assets/ground.png",
                    "web/assets/soldier.png",
                    "web/style.css",
                    "config.example.json",
                    ".github/workflows/ci.yml",
                }
                self.assertTrue(required <= names, required - names)
                self.assertFalse(
                    {"config.json", "autosave.json", "savegame.json", "LICENSE"} & names
                )
                self.assertFalse(
                    any(
                        name.startswith(("original/", "evidence/", ".tools/", ".git/"))
                        or "__pycache__" in name
                        for name in names
                    )
                )
            self.assertTrue(result.with_suffix(".zip.sha256").exists())

    def test_archive_is_reproducible(self):
        with tempfile.TemporaryDirectory() as temporary:
            first = build_release(Path(temporary) / "first.zip")
            second = build_release(Path(temporary) / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_release_version_cannot_escape_output_directory(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "package.json").write_text(json.dumps({"version": "../../unexpected"}))
            with self.assertRaises(ValueError):
                build_release(root=root)

    def test_windows_launcher_uses_crlf_in_archive(self):
        with tempfile.TemporaryDirectory() as temporary:
            result = build_release(Path(temporary) / "source.zip")
            with zipfile.ZipFile(result) as archive:
                name = next(name for name in archive.namelist() if name.endswith("/START_GAME.bat"))
                data = archive.read(name)
                self.assertIn(b"\r\n", data)
                self.assertNotIn(b"\n", data.replace(b"\r\n", b""))


if __name__ == "__main__":
    unittest.main()
