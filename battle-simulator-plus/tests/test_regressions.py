import json
import random
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from game.commanders import NetworkCommander, ProviderConfig, validate_key
from game.engine import SCENARIOS, Battle
from game.storage import atomic_json, read_json
from start import Session, StaleStateError


def wait_for_turn(session):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        with session.lock:
            if session.battle.phase != "enemy":
                return
        time.sleep(0.01)
    raise AssertionError("Enemy worker failed to release the turn")


class RegressionTests(unittest.TestCase):
    def test_interrupted_move_logs_actual_position_and_path(self):
        b = Battle()
        blue, red = b.unit("b1"), b.unit("r1")
        blue.x, blue.y = 3, 5
        red.x, red.y, red.hp = 4, 5, 1
        b.apply(blue.id, {"type": "guard"})
        b.end_player_turn()
        b.apply(red.id, {"type": "move", "x": 4, "y": 2})
        event = next(e for e in b.events if e["kind"] == "move")
        self.assertEqual(tuple(event["end"]), red.pos)
        self.assertEqual(tuple(event["path"][-1]), red.pos)
        self.assertEqual(len(event["path"]), 1)
        self.assertIn("прервано", event["text"])

    def test_invalid_turn_transition_is_atomic(self):
        b = Battle()
        before = b.save()
        with self.assertRaises(ValueError):
            b.end_enemy_turn()
        self.assertEqual(b.save(), before)

    def test_victory_is_logged_once(self):
        b = Battle()
        for u in b.living("red"):
            u.hp = u.ap = 0
        b.check_victory()
        before = b.save()
        b.check_victory()
        self.assertEqual(b.save(), before)

    def test_finished_red_turn_is_restorable(self):
        b = Battle()
        b.end_player_turn()
        for u in b.living("blue"):
            u.hp = u.ap = 0
        b.check_victory()
        self.assertEqual(Battle.restore(b.save()).winner, "red")

    def test_corrupted_geometry_types_and_ids_are_rejected(self):
        b = Battle()
        corruptions = [
            (lambda d: d["events"][0].update(end=[float("nan"), 2])),
            (lambda d: d["events"][0].update(end=[99, 2])),
            (lambda d: d["events"][0].update(path="invalid")),
            (lambda d: d["events"][0].update(round=0)),
            (lambda d: d["events"][0].update(id=999)),
            (lambda d: d["events"][0].update(unit=[])),
            (lambda d: d["units"][0].update(role="medic")),
            (lambda d: d["units"][0].update(id=[])),
            (lambda d: d.update(points=[])),
            (lambda d: d.update(score=None)),
            (lambda d: d.update(events=None)),
            (lambda d: d.update(scenario=[])),
            (
                lambda d: d["actions"].append(
                    {
                        "round": 1,
                        "team": "blue",
                        "unit": "b1",
                        "action": {"type": "move", "x": True, "y": 2},
                    }
                )
            ),
        ]
        for corrupt in corruptions:
            data = b.save()
            corrupt(data["battle"])
            with self.subTest(data=data), self.assertRaises(ValueError):
                Battle.restore(data)

    def test_random_legal_play_preserves_rules_and_save_roundtrips(self):
        for seed in range(30):
            rng = random.Random(seed)
            b = Battle(scenario=list(SCENARIOS)[seed % 3])
            while b.phase != "finished":
                team = "blue" if b.phase == "player" else "red"
                ready = [u for u in b.living(team) if u.ap]
                if ready:
                    u = rng.choice(ready)
                    b.apply(u.id, rng.choice(b.legal_actions(u)))
                elif team == "blue":
                    b.end_player_turn()
                else:
                    b.end_enemy_turn()
                positions = [u.pos for u in b.living()]
                self.assertEqual(len(set(positions)), len(positions))
                self.assertFalse(set(positions) & b.walls)
                self.assertTrue(all(0 <= u.hp <= u.spec["hp"] and 0 <= u.ap <= 2 for u in b.units))
                if b.phase in ("player", "finished"):
                    restored = Battle.restore(json.loads(json.dumps(b.save())))
                    self.assertEqual(restored.score, b.score)
                    self.assertEqual(restored.actions, b.actions)

    def test_state_cache_is_isolated_and_detects_undo_and_load(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            first = s.state()
            first["units"][0]["hp"] = 0
            self.assertEqual(s.state()["units"][0]["hp"], 90)
            version = s.state()
            small = s.state(version["state_revision"], version["session_id"])
            self.assertTrue(small["unchanged"])
            self.assertNotIn("units", small)
            s.mutate("/api/action", {"unit": "b1", "action": {"type": "guard"}})
            next_state = s.state(version["state_revision"], version["session_id"])
            self.assertNotIn("unchanged", next_state)
            self.assertGreater(next_state["state_revision"], version["state_revision"])
            s.mutate("/api/undo", {})
            self.assertEqual(s.state()["units"][0]["ap"], 2)

    def test_stale_client_cannot_execute_an_action(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            view = s.state()
            s.mutate("/api/action", {"unit": "b1", "action": {"type": "guard"}})
            before = s.battle.save()
            with self.assertRaises(StaleStateError):
                s.mutate(
                    "/api/action",
                    {
                        "unit": "b2",
                        "action": {"type": "guard"},
                        "expected_revision": view["state_revision"],
                        "expected_session": view["session_id"],
                    },
                )
            self.assertEqual(s.battle.save(), before)

    def test_own_winning_action_can_be_undone(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            for u in s.battle.living("red"):
                u.hp = u.ap = 0
            s.battle.units[4].hp = 1
            s.battle.unit("b1").x, s.battle.unit("b1").y = 12, 2
            s.mutate("/api/action", {"unit": "b1", "action": {"type": "attack", "target": "r1"}})
            self.assertTrue(s.state()["can_undo"])
            s.mutate("/api/undo", {})
            self.assertEqual(s.battle.phase, "player")
            self.assertEqual(s.battle.unit("r1").hp, 1)

    def test_execution_failure_rolls_back_and_releases_turn(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            before = [u.pos for u in s.battle.units]

            def broken(battle, team, orders):
                battle.apply("r1", {"type": "move", "x": 11, "y": 2}, "red")
                raise RuntimeError("Injected mid-turn failure")

            with patch("start.execute_plan", side_effect=broken):
                s.launch_enemy()
                wait_for_turn(s)
            self.assertEqual([u.pos for u in s.battle.units], before)
            self.assertEqual(s.battle.round, 2)
            self.assertTrue(s.ai["fallback"])

    def test_plan_logging_survives_unit_killed_by_overwatch(self):
        b = Battle()
        blue, red = b.unit("b1"), b.unit("r1")
        blue.x, blue.y = 3, 5
        red.x, red.y, red.hp = 4, 5, 1
        b.apply("b1", {"type": "guard"})
        b.end_player_turn()

        def move_then_stop(battle, uid, order):
            return {"type": "move", "x": 4, "y": 2} if battle.unit(uid) else None

        with patch("game.commanders.choose_action", side_effect=move_then_stop):
            Session.resolve_enemy(b, [{"unit": "r1", "intent": "capture", "target": "A"}])
        self.assertEqual(red.hp, 0)
        self.assertEqual(b.phase, "player")

    def test_api_key_errors_never_echo_credentials(self):
        for value in (
            "secret\nInjected",
            "secret\rInjected",
            "secret with spaces",
            "секрет_не_ascii",
        ):
            with self.subTest(value=value), self.assertRaises(ValueError) as caught:
                validate_key(value)
            self.assertNotIn(value, str(caught.exception))

    def test_malformed_ollama_envelope_is_a_clean_provider_error(self):
        with patch("game.commanders.request_json", return_value={"message": None}):
            with self.assertRaises(ValueError):
                NetworkCommander(ProviderConfig(provider="ollama")).plan(Battle(), "red")

    def test_atomic_writer_preserves_previous_file_on_failure(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "config.json"
            atomic_json(path, {"ok": True})
            with self.assertRaises(ValueError):
                atomic_json(path, {"invalid": float("nan")})
            self.assertEqual(read_json(path), {"ok": True})
            self.assertFalse(list(Path(root).glob("*.tmp")))

    def test_json_reader_rejects_large_and_invalid_files(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / "save.json"
            path.write_bytes(b"{}" * 100)
            with self.assertRaises(ValueError):
                read_json(path, 10)
            path.write_bytes(b"\xff")
            with self.assertRaises(ValueError):
                read_json(path)


if __name__ == "__main__":
    unittest.main()
