"""A provider returns squad intentions; the engine alone executes legal actions.

Implement Commander.plan(battle, team) to integrate another inference backend.
No generated text is shown as character dialogue or executed as code.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from .engine import HEIGHT, TERRAIN, WIDTH, Battle, distance

INTENTS = ("capture", "fight", "support", "hold")
ORDER_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["orders"],
    "properties": {
        "orders": {
            "type": "array",
            "minItems": 1,
            "maxItems": 4,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["unit", "intent", "target"],
                "properties": {
                    "unit": {"type": "string"},
                    "intent": {"type": "string", "enum": list(INTENTS)},
                    "target": {"type": "string"},
                },
            },
        }
    },
}
SYSTEM_PROMPT = """You command one squad in a deterministic turn-based tactical game.
Return ONLY JSON: {"orders":[{"unit":"r1","intent":"capture","target":"A"}]}.
One order per living friendly unit. No dialogue, commentary, chain of thought or invented IDs.
Intent capture: target a control point A/B/C. Intent fight: target a living enemy ID.
Intent support: target a living friendly ID. Intent hold: target the unit's own ID.
The tactical executor uses two action points per unit, chooses legal paths, shoots enemies,
heals allies, uses abilities, and guards. You choose its strategic goal, not coordinates.
Win by holding points (5 points each per full round, contested gives zero), reaching 60,
or eliminating the enemy. At round 18 highest score wins; HP breaks ties.
Spread out to capture different points. Focus exposed low-HP enemies when a kill is feasible.
Walls block shots; cover reduces damage by 5. Guard reduces damage by 7 and reacts to movement.
Distances are Manhattan. Units have full shared battlefield information, no hidden enemies.
Role skills: assault grenade 24 area damage; ranger 35 shot ignores cover and costs 2 AP;
medic heals 28 in range 3; heavy deals 18 and suppresses one enemy AP next turn.
Skills have a two-own-turn cooldown. Output must follow the supplied JSON schema."""


@dataclass
class ProviderConfig:
    provider: str = "builtin"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "gemma4:e4b"
    api_key_env: str = "BATTLE_API_KEY"
    timeout: int = 40
    structured: bool = True
    thinking: bool = False

    @classmethod
    def validate(cls, raw):
        if not isinstance(raw, dict):
            raise ValueError("Настройки должны быть объектом")
        values = {k: raw[k] for k in cls.__dataclass_fields__ if k in raw}
        c = cls(**values)
        if c.provider not in ("builtin", "ollama", "openai"):
            raise ValueError("Неизвестный провайдер")
        if not isinstance(c.model, str) or not 1 <= len(c.model.strip()) <= 150:
            raise ValueError("Укажите название модели")
        if not isinstance(c.base_url, str) or len(c.base_url) > 500:
            raise ValueError("Некорректный адрес сервера")
        parsed = urllib.parse.urlparse(c.base_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Нужен адрес http:// или https:// без ключей и параметров")
        if not isinstance(c.api_key_env, str) or not re.fullmatch(
            r"[A-Za-z_][A-Za-z0-9_]{0,80}", c.api_key_env
        ):
            raise ValueError("Некорректное имя переменной окружения для ключа")
        if (
            type(c.timeout) is not int
            or not 5 <= c.timeout <= 120
            or type(c.structured) is not bool
            or type(c.thinking) is not bool
        ):
            raise ValueError("Тайм-аут: 5–120 секунд; переключатели: true/false")
        c.model, c.base_url = c.model.strip(), c.base_url.rstrip("/")
        return c


class Commander(Protocol):
    def plan(self, battle: Battle, team: str) -> list[dict]: ...


class BuiltinCommander:
    def plan(self, battle, team):
        reserved = {}
        orders = []
        for u in battle.living(team):
            needy = [v for v in battle.living(team) if v.hp < v.spec["hp"] * 0.6]
            if u.role == "medic" and needy:
                target = min(needy, key=lambda v: distance(v.pos, u.pos))
                orders.append({"unit": u.id, "intent": "support", "target": target.id})
                continue
            point = min(
                battle.points,
                key=lambda p: (
                    distance(u.pos, (p["x"], p["y"]))
                    + reserved.get(p["id"], 0) * 5
                    + (6 if p["owner"] == team and not p["contested"] else 0)
                ),
            )
            reserved[point["id"]] = reserved.get(point["id"], 0) + 1
            orders.append({"unit": u.id, "intent": "capture", "target": point["id"]})
        return orders


def validate_orders(raw, battle, team):
    if (
        not isinstance(raw, dict)
        or not isinstance(raw.get("orders"), list)
        or not 1 <= len(raw["orders"]) <= 4
    ):
        raise ValueError("Модель вернула некорректный план")
    valid, used = [], set()
    for order in raw["orders"]:
        if not isinstance(order, dict) or any(
            not isinstance(order.get(k), str) for k in ("unit", "intent", "target")
        ):
            raise ValueError("Модель вернула некорректный приказ")
        u = battle.unit(order["unit"])
        intent, target = order["intent"], order["target"]
        if not u or u.team != team or u.id in used or intent not in INTENTS:
            raise ValueError("В плане неизвестный или повторный боец")
        if intent == "capture":
            ok = target in "ABC" and len(target) == 1
        elif intent == "hold":
            ok = target == u.id
        else:
            v = battle.unit(target)
            ok = v is not None and ((v.team == team) if intent == "support" else (v.team != team))
        if not ok:
            raise ValueError("В плане недопустимая цель")
        valid.append({k: order[k] for k in ("unit", "intent", "target")})
        used.add(u.id)
    # Partial plans are completed deterministically, never by inventing actions.
    return valid + [o for o in BuiltinCommander().plan(battle, team) if o["unit"] not in used]


def validate_key(key):
    if not isinstance(key, str) or len(key) > 500 or any(not 33 <= ord(c) <= 126 for c in key):
        raise ValueError("API-ключ должен быть одной строкой без пробелов и управляющих символов")
    return key


def request_json(url, body=None, key="", timeout=40):
    validate_key(key)
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if key:
        headers["Authorization"] = "Bearer " + key
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8") if body is not None else None, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            payload = response.read(1_048_577)
        if len(payload) > 1_048_576:
            raise ValueError("Ответ модели слишком большой")
        result = json.loads(payload)
        if not isinstance(result, dict):
            raise ValueError("Сервер модели должен вернуть JSON-объект")
        return result
    except urllib.error.HTTPError as e:
        code = e.code
        e.close()
        raise ValueError(f"Сервер модели вернул HTTP {code}") from None
    except (urllib.error.URLError, TimeoutError, OSError):
        raise ValueError("Сервер модели недоступен или превышен тайм-аут") from None
    except (json.JSONDecodeError, UnicodeError):
        raise ValueError("Сервер вернул некорректный JSON") from None


class NetworkCommander:
    def __init__(self, config, session_key=""):
        self.config = config
        self.session_key = session_key

    def plan(self, battle, team):
        c = self.config
        briefing = {
            "team": team,
            "round": battle.round,
            "score": battle.score,
            "points": battle.points,
            "walls": sorted(battle.walls),
            "cover": sorted(battle.cover),
            "board": [WIDTH, HEIGHT],
            "units": [
                {
                    "id": u.id,
                    "team": u.team,
                    "role": u.role,
                    "position": u.pos,
                    "hp": u.hp,
                    "max_hp": u.spec["hp"],
                    "ap": u.ap,
                    "cooldown": u.cooldown,
                    "guard": u.guard,
                    "range": u.spec["range"],
                    "damage": u.spec["damage"],
                    "move": u.spec["move"],
                }
                for u in battle.living()
            ],
        }
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": json.dumps(
                    {"battle": briefing, "output_schema": ORDER_SCHEMA}, separators=(",", ":")
                ),
            },
        ]
        body = {"model": c.model, "messages": messages, "stream": False}
        if c.provider == "ollama":
            body.update(
                {
                    "think": c.thinking,
                    "options": {"temperature": 0.15, "num_predict": 650, "num_ctx": 8192},
                }
            )
            if c.structured:
                body["format"] = ORDER_SCHEMA
            response = request_json(c.base_url + "/api/chat", body, timeout=c.timeout)
            message = response.get("message")
            content = message.get("content", "") if isinstance(message, dict) else ""
        else:
            if c.structured:
                body["response_format"] = {"type": "json_object"}
            response = request_json(
                c.base_url + "/chat/completions",
                body,
                self.session_key or os.environ.get(c.api_key_env, ""),
                c.timeout,
            )
            try:
                content = response["choices"][0]["message"]["content"]
            except (KeyError, IndexError, TypeError):
                raise ValueError("В ответе сервера нет результата модели") from None
        if not isinstance(content, str) or len(content) > 16000:
            raise ValueError("Пустой или слишком большой ответ модели")
        # Support ordinary fenced JSON, but never scrape arbitrary prose or reasoning.
        text = content.strip()
        if text.startswith("```") and text.endswith("```"):
            text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
        try:
            return validate_orders(json.loads(text), battle, team)
        except (json.JSONDecodeError, TypeError):
            raise ValueError("Модель не вернула JSON с боевым планом") from None


def get_commander(config, session_key=""):
    return (
        BuiltinCommander()
        if config.provider == "builtin"
        else NetworkCommander(config, session_key)
    )


@lru_cache(maxsize=512)
def _goal_distances(scenario, goal):
    walls = TERRAIN[scenario]["walls"]
    paths, queue = {goal: 0}, deque([goal])
    while queue:
        x, y = queue.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            p = x + dx, y + dy
            if 0 <= p[0] < WIDTH and 0 <= p[1] < HEIGHT and p not in walls and p not in paths:
                paths[p] = paths[(x, y)] + 1
                queue.append(p)
    return paths


def goal_distances(battle, goal):
    return _goal_distances(battle.scenario, tuple(goal))


def choose_action(battle, uid, order=None):
    u = battle.unit(uid)
    if not u or not u.ap:
        return None
    order = order or next(o for o in BuiltinCommander().plan(battle, u.team) if o["unit"] == uid)
    point = next((p for p in battle.points if p["id"] == order["target"]), None)
    target = battle.unit(order["target"])
    if order["intent"] == "capture" and point:
        goal = point["x"], point["y"]
    elif target:
        goal = target.pos
    else:
        goal = u.pos
    paths = goal_distances(battle, goal)
    enemies = [v for v in battle.living() if v.team != u.team]
    attack_weight = 1.25 if battle.difficulty == "easy" and u.team == "red" else 1.8

    def value(a):
        kind = a["type"]
        if kind == "attack" or (kind == "skill" and u.role in ("heavy", "ranger")):
            v = battle.unit(a["target"])
            score = a["damage"] * attack_weight / a["cost"] + (60 if v.hp <= a["damage"] else 0)
            if order["intent"] == "fight" and v.id == order["target"]:
                score += 12
            if kind == "skill" and u.role == "heavy" and not v.suppressed:
                score += 15
            return score
        if kind == "skill" and u.role == "medic":
            v = battle.unit(a["target"])
            return a["heal"] * (2.5 if v.hp < v.spec["hp"] * 0.5 else 1.5)
        if kind == "skill" and u.role == "assault":
            return sum(
                battle.damage(battle.unit(vid), 24, True) * 1.65
                + (60 if battle.unit(vid).hp <= battle.damage(battle.unit(vid), 24, True) else 0)
                for vid in a["targets"]
            )
        if kind == "move":
            p = a["x"], a["y"]
            before, after = paths.get(u.pos, 99), paths.get(p, 99)
            if order["intent"] == "hold":
                return -10
            if order["intent"] == "capture":
                before, after = max(0, before - 1), max(0, after - 1)
            elif order["intent"] == "support":
                before, after = max(0, before - 3), max(0, after - 3)
            score = (before - after) * 11 + (6 if p in battle.cover else 0)
            if before == 0:
                score -= 12
            if battle.difficulty == "hard" and u.team == "red":
                threats = sum(
                    distance(v.pos, p) <= v.spec["range"] and battle.line_of_sight(v.pos, p)
                    for v in enemies
                )
                score -= threats * (3 if u.hp > u.spec["hp"] * 0.5 else 8)
                if u.ap >= 2:
                    shootable = [
                        v
                        for v in enemies
                        if distance(v.pos, p) <= u.spec["range"] and battle.line_of_sight(p, v.pos)
                    ]
                    if shootable:
                        score += 16 + (
                            30 if any(v.hp <= u.spec["damage"] for v in shootable) else 0
                        )
            if u.role == "ranger" and any(
                distance(v.pos, p) <= u.spec["range"] and battle.line_of_sight(p, v.pos)
                for v in enemies
            ):
                score += 6
            return score
        if kind == "guard":
            in_sector = any(distance(v.pos, u.pos) <= u.spec["range"] + 2 for v in enemies)
            return (
                9
                + (10 if in_sector else 0)
                + (5 if order["intent"] == "hold" else 0)
                + (
                    8
                    if battle.difficulty == "hard" and u.team == "red" and u.hp < u.spec["hp"] * 0.4
                    else 0
                )
            )
        return -100

    actions = battle.legal_actions(u)
    return max(actions, key=value) if actions else None


def execute_plan(battle, team, orders):
    for order in orders:
        for _ in range(2):
            if battle.phase == "finished":
                return
            action = choose_action(battle, order["unit"], order)
            if action:
                battle.apply(order["unit"], action, team)
