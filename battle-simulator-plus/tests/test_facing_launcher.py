import json
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

from game.engine import Battle
from launcher import ROOT, acquire_lock, existing_url
from start import GameServer, Session


class FacingTests(unittest.TestCase):
    def test_move_save_and_undo_facing(self):
        with tempfile.TemporaryDirectory() as directory:
            session = Session(Path(directory))
            self.assertEqual(session.battle.unit("r1").facing, 180)
            session.mutate(
                "/api/action", {"unit": "b1", "action": {"type": "move", "x": 1, "y": 1}}
            )
            self.assertEqual(session.battle.unit("b1").facing, 270)
            restored = Battle.restore(json.loads(json.dumps(session.battle.save())))
            self.assertEqual(restored.unit("b1").facing, 270)
            session.mutate("/api/undo", {})
            self.assertEqual(session.battle.unit("b1").facing, 0)

    def test_attack_and_reaction_face_the_target(self):
        battle = Battle()
        blue, red = battle.unit("b1"), battle.unit("r1")
        blue.x, blue.y = 3, 5
        red.x, red.y = 3, 6
        battle.apply("b1", {"type": "attack", "target": "r1"})
        self.assertEqual(blue.facing, 90)
        battle.apply("b1", {"type": "guard"})
        battle.end_player_turn()
        battle.apply("r1", {"type": "move", "x": 4, "y": 6})
        self.assertEqual(blue.facing, 45)
        self.assertEqual(red.facing, 0)

    def test_old_saves_and_invalid_facing(self):
        saved = Battle().save()
        for unit in saved["battle"]["units"]:
            del unit["facing"]
        restored = Battle.restore(saved)
        self.assertEqual(restored.unit("r1").facing, 180)
        for value in [True, -1, 360, "90", float("nan")]:
            invalid = restored.save()
            invalid["battle"]["units"][0]["facing"] = value
            with self.assertRaises(ValueError):
                Battle.restore(invalid)


class LauncherTests(unittest.TestCase):
    def test_another_server_cannot_share_the_same_port(self):
        with tempfile.TemporaryDirectory() as directory:
            server = GameServer(("127.0.0.1", 0), Session(Path(directory)))
            try:
                with self.assertRaises(OSError):
                    duplicate = GameServer(server.server_address, server.session)
                    duplicate.server_close()
            finally:
                server.server_close()

    def test_lock_released_when_owner_closes(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "lock"
            first = acquire_lock(path)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(acquire_lock(path))
            finally:
                first.close()
            second = acquire_lock(path)
            self.assertIsNotNone(second)
            second.close()

    def test_launch_reuse_assets_and_shutdown(self):
        with tempfile.TemporaryDirectory(prefix="rift profile ") as directory:
            command = [
                sys.executable,
                str(ROOT / "launcher.py"),
                "--no-browser",
                "--data-dir",
                directory,
            ]
            process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
            try:
                endpoint = Path(directory) / ".local" / "launcher.json"
                deadline = time.monotonic() + 10
                url = None
                while time.monotonic() < deadline and not url:
                    url = existing_url(endpoint)
                    time.sleep(0.05)
                self.assertIsNotNone(url)
                second = subprocess.run(command, capture_output=True, timeout=10)
                self.assertEqual(second.returncode, 0, second.stderr)
                self.assertEqual(existing_url(endpoint), url)
                for asset in ["/assets/ground.png", "/assets/soldier.png", "/battlefield-art.js"]:
                    with urllib.request.urlopen(url + asset) as response:
                        self.assertEqual(response.status, 200)
                        self.assertGreater(len(response.read()), 100)
                session_id = json.loads(endpoint.read_text())["session_id"]
                request = urllib.request.Request(
                    url + "/api/shutdown",
                    json.dumps({"expected_session": session_id}).encode(),
                    {"Content-Type": "application/json", "X-Battle-Client": "1"},
                )
                with urllib.request.urlopen(request) as response:
                    self.assertTrue(json.load(response)["ok"])
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertFalse(endpoint.exists())
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                process.stderr.close()
