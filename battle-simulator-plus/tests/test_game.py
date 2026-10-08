import json
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from game.commanders import (
    BuiltinCommander,
    NetworkCommander,
    ProviderConfig,
    execute_plan,
    validate_orders,
)
from game.engine import SCENARIOS, Battle
from start import GameServer, Session


def duel(role="assault"):
    b = Battle()
    actor = next(u for u in b.units if u.team == "blue" and u.role == role)
    actor.x, actor.y = 3, 5
    enemy = b.unit("r1")
    enemy.x, enemy.y = 4, 5
    return b, actor, enemy


class RulesTests(unittest.TestCase):
    def test_movement_is_bounded_by_path_and_consumes_ap(self):
        b = Battle()
        b.apply("b1", {"type": "move", "x": 4, "y": 2}, "blue")
        self.assertEqual(b.unit("b1").ap, 1)
        self.assertEqual(b.unit("b1").pos, (4, 2))
        with self.assertRaises(ValueError):
            b.apply("b1", {"type": "move", "x": 10, "y": 2}, "blue")
        self.assertEqual(b.unit("b1").ap, 1)

    def test_walls_occupancy_boundaries_and_noninteger_moves(self):
        b = Battle()
        b.unit("b1").x, b.unit("b1").y = 5, 2
        for x, y in ((6, 2), (14, 2), (-1, 2), (True, 2), (5.0, 2)):
            with self.subTest(x=x, y=y), self.assertRaises(ValueError):
                b.apply("b1", {"type": "move", "x": x, "y": y})

    def test_line_of_sight_blocks_walls_and_corners(self):
        b = Battle()
        self.assertFalse(b.line_of_sight((5, 2), (7, 2)))
        self.assertFalse(b.line_of_sight((5, 1), (6, 0)))
        self.assertTrue(b.line_of_sight((2, 4), (6, 4)))
        self.assertEqual(b.line_of_sight((3, 3), (9, 9)), b.line_of_sight((9, 9), (3, 3)))

    def test_attacks_are_deterministic_and_ignore_client_damage(self):
        b, u, enemy = duel()
        hp = enemy.hp
        b.apply(u.id, {"type": "attack", "target": enemy.id, "damage": 99999, "cost": 0})
        self.assertEqual(enemy.hp, hp - u.spec["damage"])
        self.assertEqual(u.ap, 1)

    def test_friendly_fire_out_of_range_dead_and_wrong_team_rejected(self):
        b, u, enemy = duel()
        for req in ({"type": "attack", "target": "b2"}, {"type": "attack", "target": "missing"}):
            with self.assertRaises(ValueError):
                b.apply(u.id, req)
        enemy.x, enemy.y = 14, 9
        with self.assertRaises(ValueError):
            b.apply(u.id, {"type": "attack", "target": enemy.id})
        with self.assertRaises(ValueError):
            b.apply("r1", {"type": "guard"})
        enemy.hp = 0
        with self.assertRaises(ValueError):
            b.apply(u.id, {"type": "attack", "target": enemy.id})

    def test_cover_and_guard_mitigate_damage(self):
        b, u, enemy = duel()
        enemy.x, enemy.y = 4, 3
        enemy.guard = True
        self.assertEqual(b.damage(enemy, 20), 8)
        b.apply(u.id, {"type": "attack", "target": enemy.id})
        self.assertEqual(enemy.hp, 82)

    def test_overwatch_fires_once_and_guard_ends_actions(self):
        b, u, enemy = duel()
        b.apply(u.id, {"type": "guard"})
        self.assertEqual(u.ap, 0)
        b.end_player_turn()
        b.apply(enemy.id, {"type": "move", "x": 4, "y": 4})
        self.assertFalse(u.reaction)
        self.assertEqual(enemy.hp, 70)
        b.apply(enemy.id, {"type": "move", "x": 4, "y": 5})
        self.assertEqual(enemy.hp, 70)

    def test_overwatch_death_interrupts_movement_path(self):
        b, u, enemy = duel()
        b.apply(u.id, {"type": "guard"})
        enemy.hp = 1
        b.end_player_turn()
        b.apply(enemy.id, {"type": "move", "x": 4, "y": 2})
        self.assertEqual(enemy.hp, 0)
        self.assertEqual(enemy.pos, (4, 4))

    def test_medic_healing_and_two_turn_cooldown(self):
        b, medic, enemy = duel("medic")
        ally = b.unit("b1")
        ally.x, ally.y, ally.hp = 2, 5, 10
        b.apply(medic.id, {"type": "skill", "target": ally.id})
        self.assertEqual(ally.hp, 38)
        self.assertEqual(medic.cooldown, 3)
        for expected in (2, 1, 0):
            b.end_player_turn()
            b.end_enemy_turn()
            self.assertEqual(medic.cooldown, expected)

    def test_sniper_skill_costs_two_and_ignores_cover(self):
        b, ranger, enemy = duel("ranger")
        enemy.x, enemy.y = 4, 3
        b.apply(ranger.id, {"type": "skill", "target": enemy.id})
        self.assertEqual(enemy.hp, 55)
        self.assertEqual(ranger.ap, 0)

    def test_suppression_reduces_next_turn_ap_once(self):
        b, heavy, enemy = duel("heavy")
        b.apply(heavy.id, {"type": "skill", "target": enemy.id})
        b.end_player_turn()
        self.assertEqual(enemy.ap, 1)
        self.assertFalse(enemy.suppressed)
        b.end_enemy_turn()
        b.end_player_turn()
        self.assertEqual(enemy.ap, 2)

    def test_grenade_area_enemy_only(self):
        b, u, enemy = duel()
        another = b.unit("r2")
        another.x, another.y = 4, 4
        friend = b.unit("b3")
        friend.x, friend.y = 3, 4
        b.apply(u.id, {"type": "skill", "x": 4, "y": 4})
        self.assertEqual(enemy.hp, 66)
        self.assertEqual(another.hp, 46)
        self.assertEqual(friend.hp, friend.spec["hp"])

    def test_contested_point_does_not_score(self):
        b = Battle()
        p = b.points[0]
        b.unit("b1").x, b.unit("b1").y = 7, 0
        b.update_points(False)
        self.assertEqual(p["owner"], "blue")
        b.unit("r1").x, b.unit("r1").y = 8, 1
        b.update_points(True)
        self.assertTrue(p["contested"])
        self.assertEqual(b.score["blue"], 0)
        b.unit("r1").x, b.unit("r1").y = 14, 1
        b.unit("b1").x, b.unit("b1").y = 1, 1
        b.update_points(True)
        self.assertEqual(p["owner"], "blue")
        self.assertEqual(b.score["blue"], 5)

    def test_elimination_and_score_victory(self):
        b, u, enemy = duel()
        for v in b.living("red"):
            v.hp = 1 if v.id == enemy.id else 0
        b.apply(u.id, {"type": "attack", "target": enemy.id})
        self.assertEqual((b.phase, b.winner), ("finished", "blue"))
        with self.assertRaises(ValueError):
            b.apply(u.id, {"type": "guard"})
        b = Battle()
        b.score = {"blue": 60, "red": 60}
        b.check_victory(end_round=True)
        self.assertEqual(b.winner, "draw")

    def test_round_limit_uses_hp_tiebreaker(self):
        b = Battle(round=18)
        b.unit("b1").hp -= 10
        b.end_player_turn()
        b.end_enemy_turn()
        self.assertEqual(b.winner, "red")

    def test_save_roundtrip_and_reject_corruption(self):
        b = Battle()
        b.apply("b1", {"type": "move", "x": 4, "y": 2})
        self.assertEqual(
            json.dumps(Battle.restore(json.loads(json.dumps(b.save()))).snapshot(), sort_keys=True),
            json.dumps(b.snapshot(), sort_keys=True),
        )
        for field, value in (("round", 999), ("phase", "enemy"), ("score", {"blue": -1, "red": 0})):
            raw = b.save()
            raw["battle"][field] = value
            with self.subTest(field=field), self.assertRaises(ValueError):
                Battle.restore(raw)
        raw = b.save()
        raw["battle"]["units"][0]["x"] = 100
        with self.assertRaises(ValueError):
            Battle.restore(raw)

    def test_all_maps_and_difficulties_complete_and_are_reproducible(self):
        results = []
        for scenario in SCENARIOS:
            for difficulty in ("easy", "normal", "hard"):
                snapshots = []
                for repeat in range(2):
                    b = Battle(scenario=scenario, difficulty=difficulty)
                    while b.phase != "finished":
                        execute_plan(b, "blue", BuiltinCommander().plan(b, "blue"))
                        if b.phase == "finished":
                            break
                        b.end_player_turn()
                        execute_plan(b, "red", BuiltinCommander().plan(b, "red"))
                        b.end_enemy_turn()
                        positions = [u.pos for u in b.living()]
                        self.assertEqual(len(set(positions)), len(positions))
                        self.assertFalse(set(positions) & b.walls)
                        self.assertLessEqual(b.round, 18)
                    self.assertTrue(b.winner)
                    snapshots.append(b.save())
                self.assertEqual(*snapshots)
                results.append(
                    {
                        "scenario": scenario,
                        "difficulty": difficulty,
                        "winner": b.winner,
                        "round": b.round,
                        "score": b.score,
                        "actions": len(b.actions),
                    }
                )
        print("\nFULL_MATCH_RESULTS=" + json.dumps(results))


class ProviderTests(unittest.TestCase):
    def test_real_http_transport_for_both_provider_protocols(self):
        observed = []
        content = json.dumps({"orders": BuiltinCommander().plan(Battle(), "red")})

        class FakeProvider(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                observed.append(
                    {"path": self.path, "body": body, "auth": self.headers.get("Authorization")}
                )
                response = (
                    {"message": {"content": content}}
                    if self.path == "/api/chat"
                    else {"choices": [{"message": {"content": content}}]}
                )
                raw = json.dumps(response).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(raw)))
                self.end_headers()
                self.wfile.write(raw)

        server = ThreadingHTTPServer(("127.0.0.1", 0), FakeProvider)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{server.server_port}"
            for provider in ("ollama", "openai"):
                config = ProviderConfig(
                    provider=provider, base_url=base if provider == "ollama" else base + "/v1"
                )
                self.assertEqual(len(NetworkCommander(config, "fake-key").plan(Battle(), "red")), 4)
            self.assertEqual([r["path"] for r in observed], ["/api/chat", "/v1/chat/completions"])
            self.assertIsNone(observed[0]["auth"])
            self.assertEqual(observed[1]["auth"], "Bearer fake-key")
            self.assertEqual(observed[1]["body"]["response_format"], {"type": "json_object"})
        finally:
            server.shutdown()
            server.server_close()

    def test_partial_valid_plan_is_completed(self):
        b = Battle()
        orders = validate_orders(
            {"orders": [{"unit": "r1", "intent": "capture", "target": "A"}]}, b, "red"
        )
        self.assertEqual(len(orders), 4)

    def test_invalid_model_orders_are_rejected(self):
        b = Battle()
        examples = [
            None,
            {},
            {"orders": []},
            {"orders": [{"unit": "b1", "intent": "capture", "target": "A"}]},
            {"orders": [{"unit": "r1", "intent": "fight", "target": "r2"}]},
            {"orders": [{"unit": "r1", "intent": "capture", "target": "X"}]},
            {"orders": [{"unit": "r1", "intent": "speak", "target": "b1"}]},
        ]
        for raw in examples:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                validate_orders(raw, b, "red")
        raw = {"orders": [{"unit": "r1", "intent": "capture", "target": "A"}] * 2}
        with self.assertRaises(ValueError):
            validate_orders(raw, b, "red")

    def test_ollama_and_openai_adapters(self):
        content = json.dumps({"orders": BuiltinCommander().plan(Battle(), "red")})
        for provider in ("ollama", "openai"):
            config = ProviderConfig(provider=provider, base_url="http://example.test/v1")
            result = (
                {"message": {"content": content}}
                if provider == "ollama"
                else {"choices": [{"message": {"content": "```json\n" + content + "\n```"}}]}
            )
            with patch("game.commanders.request_json", return_value=result) as request:
                orders = NetworkCommander(config).plan(Battle(), "red")
                self.assertEqual(len(orders), 4)
                url, payload = request.call_args.args[:2]
                self.assertTrue(
                    url.endswith("/api/chat" if provider == "ollama" else "/chat/completions")
                )
                self.assertFalse(payload["stream"])
                self.assertIn("format" if provider == "ollama" else "response_format", payload)

    def test_provider_config_validation(self):
        for raw in (
            {"provider": "unknown"},
            {"timeout": True},
            {"base_url": "file:///private"},
            {"base_url": "http://key:secret@example.com"},
            {"structured": "true"},
            {"api_key_env": "invalid-name"},
        ):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                ProviderConfig.validate(raw)

    def test_failed_neural_turn_falls_back_without_blocking(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            s.config = ProviderConfig(provider="ollama")
            with patch("game.commanders.request_json", side_effect=ValueError("Mock timeout")):
                s.launch_enemy()
                deadline = time.monotonic() + 4
                while s.battle.phase == "enemy" and time.monotonic() < deadline:
                    time.sleep(0.01)
            with s.lock:  # Turn completion and autosave are committed under this lock.
                self.assertEqual(s.battle.round, 2)
                self.assertEqual(s.battle.phase, "player")
                self.assertTrue(s.ai["fallback"])
                self.assertTrue((Path(root) / "autosave.json").exists())

    def test_abandoned_response_cannot_mutate_new_match(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            s.config = ProviderConfig(provider="ollama")
            entered, release = threading.Event(), threading.Event()

            def delayed(*args, **kwargs):
                entered.set()
                release.wait(3)
                return {
                    "message": {
                        "content": json.dumps({"orders": BuiltinCommander().plan(Battle(), "red")})
                    }
                }

            with patch("game.commanders.request_json", side_effect=delayed):
                s.launch_enemy()
                self.assertTrue(entered.wait(2))
                s.mutate("/api/new", {"scenario": "relay"})
                before = s.battle.save()
                release.set()
                deadline = time.monotonic() + 2
                while s.inflight and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(s.battle.save(), before)

    def test_manual_fallback_does_not_wait_for_neural_response(self):
        with tempfile.TemporaryDirectory() as root:
            s = Session(Path(root))
            s.config = ProviderConfig(provider="ollama")
            entered, release = threading.Event(), threading.Event()

            def delayed(*args, **kwargs):
                entered.set()
                release.wait(3)
                raise ValueError("Mock timeout")

            with patch("game.commanders.request_json", side_effect=delayed):
                s.launch_enemy()
                self.assertTrue(entered.wait(2))
                s.fallback_now()
                self.assertEqual(s.battle.phase, "player")
                before = s.battle.save()
                self.assertTrue(s.inflight)
                release.set()
                deadline = time.monotonic() + 2
                while s.inflight and time.monotonic() < deadline:
                    time.sleep(0.01)
                self.assertEqual(s.battle.save(), before)


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.session = Session(Path(self.tmp.name))
        self.server = GameServer(("127.0.0.1", 0), self.session)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()
        self.tmp.cleanup()

    def call(self, route, body=None, origin=None, header=True):
        headers = {"Content-Type": "application/json"}
        if header:
            headers["X-Battle-Client"] = "1"
        if origin:
            headers["Origin"] = origin
        req = urllib.request.Request(
            self.base + route, json.dumps(body).encode() if body is not None else None, headers
        )
        with urllib.request.urlopen(req, timeout=4) as response:
            return json.load(response)

    def test_browser_api_actions_undo_save_load(self):
        original = self.call("/api/state")
        moved = self.call("/api/action", {"unit": "b1", "action": {"type": "move", "x": 4, "y": 2}})
        self.assertTrue(moved["can_undo"])
        restored = self.call("/api/undo", {})
        self.assertEqual(restored["units"], original["units"])
        self.call("/api/save", {})
        self.call("/api/new", {"scenario": "crossroads"})
        loaded = self.call("/api/load", {})
        self.assertEqual(loaded["scenario"], "foundry")
        autosaved = self.call("/api/load", {"slot": "auto"})
        self.assertEqual(autosaved["scenario"], "crossroads")

    def test_cross_origin_and_headerless_mutations_rejected(self):
        for origin, header in (("http://attacker.example", True), (None, False)):
            with self.subTest(origin=origin), self.assertRaises(urllib.error.HTTPError) as e:
                self.call("/api/new", {}, origin, header)
            self.assertEqual(e.exception.code, 403)
            e.exception.close()

    def test_keys_are_not_saved_or_exposed(self):
        self.call("/api/config", {"provider": "openai", "api_key": "test-only-secret"})
        self.assertNotIn("test-only-secret", (Path(self.tmp.name) / "config.json").read_text())
        self.assertNotIn("test-only-secret", json.dumps(self.call("/api/config")))
        self.assertNotIn("test-only-secret", json.dumps(self.call("/api/export")))
        self.call("/api/config", {"clear_key": True})
        self.assertFalse(self.call("/api/config")["has_key"])

    def test_model_connection_test_does_not_change_saved_config(self):
        before = asdict(self.session.config)
        response = self.call(
            "/api/test-model", {"provider": "builtin", "model": "test-unsaved-choice"}
        )
        self.assertEqual(len(response["orders"]), 4)
        self.assertEqual(asdict(self.session.config), before)
        self.assertFalse((Path(self.tmp.name) / "config.json").exists())

    def test_invalid_action_is_atomic(self):
        before = self.session.battle.save()
        with self.assertRaises(urllib.error.HTTPError) as e:
            self.call(
                "/api/action", {"unit": "b1", "action": {"type": "attack", "target": "missing"}}
            )
        e.exception.close()
        self.assertEqual(self.session.battle.save(), before)

    def test_static_paths_do_not_allow_arbitrary_files(self):
        with urllib.request.urlopen(self.base + "/", timeout=3) as r:
            self.assertIn(b"RIFT", r.read())
        with self.assertRaises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(self.base + "/../config.json", timeout=3)
        self.assertEqual(e.exception.code, 404)
        e.exception.close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
