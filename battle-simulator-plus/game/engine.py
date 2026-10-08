from __future__ import annotations

from collections import deque
from copy import deepcopy
from dataclasses import asdict, dataclass, field
from functools import lru_cache
from math import atan2, degrees

WIDTH, HEIGHT = 16, 11
POINTS_TO_WIN, ROUND_LIMIT = 60, 18
CLASSES = {
    "assault": {
        "title": "Штурмовик",
        "hp": 90,
        "damage": 20,
        "range": 4,
        "move": 3,
        "skill": "Граната",
        "description": "24 урона врагам в радиусе одной клетки. Дальность броска: 4.",
    },
    "ranger": {
        "title": "Разведчик",
        "hp": 70,
        "damage": 23,
        "range": 6,
        "move": 4,
        "skill": "Точный выстрел",
        "description": "35 урона, игнорирует укрытие. Стоимость: 2 ОД.",
    },
    "medic": {
        "title": "Медик",
        "hp": 75,
        "damage": 15,
        "range": 4,
        "move": 3,
        "skill": "Лечение",
        "description": "Восстанавливает 28 здоровья союзнику в пределах 3 клеток.",
    },
    "heavy": {
        "title": "Тяжёлый боец",
        "hp": 115,
        "damage": 26,
        "range": 4,
        "move": 2,
        "skill": "Подавление",
        "description": "18 урона и минус 1 ОД цели в её следующем ходу.",
    },
}
SCENARIOS = {
    "foundry": {
        "name": "Промзона",
        "subtitle": "Заброшенный завод · сектор 07",
        "brief": "Займите узлы связи в заводском дворе. Центральный узел открыт для обстрела; фланги дают укрытие.",
        "walls": [(6, 1), (6, 2), (9, 8), (9, 9), (6, 5), (9, 5)],
        "cover": [
            (4, 2),
            (4, 3),
            (11, 7),
            (11, 8),
            (7, 3),
            (8, 7),
            (4, 7),
            (11, 3),
            (7, 8),
            (8, 2),
        ],
        "points": [(7, 1), (8, 5), (8, 9)],
    },
    "crossroads": {
        "name": "Перекрёсток",
        "subtitle": "Разрушенный город · сектор 12",
        "brief": "Три прохода через город. Используйте здания для защиты, но следите за длинными линиями огня на улицах.",
        "walls": [
            (5, 2),
            (6, 2),
            (5, 3),
            (10, 7),
            (9, 7),
            (10, 8),
            (5, 7),
            (5, 8),
            (10, 2),
            (10, 3),
        ],
        "cover": [(4, 4), (11, 6), (7, 1), (8, 9), (6, 6), (9, 4), (7, 7), (8, 3)],
        "points": [(8, 1), (7, 5), (7, 9)],
    },
    "relay": {
        "name": "Релейная станция",
        "subtitle": "Пограничная станция · сектор 03",
        "brief": "Разделите отряд между флангами. Центральные сооружения перекрывают огонь и вынуждают менять позиции.",
        "walls": [(7, 3), (8, 3), (7, 7), (8, 7), (6, 5), (9, 5)],
        "cover": [(5, 1), (10, 9), (5, 9), (10, 1), (6, 3), (9, 7), (6, 7), (9, 3), (7, 5), (8, 5)],
        "points": [(8, 1), (7, 5), (7, 9)],
    },
}
TERRAIN = {
    key: {"walls": frozenset(value["walls"]), "cover": frozenset(value["cover"])}
    for key, value in SCENARIOS.items()
}


def distance(a, b):
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


@lru_cache(maxsize=4096)
def clear_line(scenario, a, b):
    walls = TERRAIN[scenario]["walls"]
    x, y = a
    dx, dy = b[0] - x, b[1] - y
    nx, ny = abs(dx), abs(dy)
    sx, sy = (1 if dx > 0 else -1), (1 if dy > 0 else -1)
    ix = iy = 0
    while ix < nx or iy < ny:
        decision = (1 + 2 * ix) * ny - (1 + 2 * iy) * nx
        if decision == 0:
            if (x + sx, y) in walls or (x, y + sy) in walls:
                return False
            x, y, ix, iy = x + sx, y + sy, ix + 1, iy + 1
        elif decision < 0:
            x, ix = x + sx, ix + 1
        else:
            y, iy = y + sy, iy + 1
        if (x, y) in walls:
            return False
    return True


def valid_cell(value):
    return (
        isinstance(value, (list, tuple))
        and len(value) == 2
        and all(type(v) is int for v in value)
        and 0 <= value[0] < WIDTH
        and 0 <= value[1] < HEIGHT
    )


@dataclass
class Unit:
    id: str
    name: str
    role: str
    team: str
    x: int
    y: int
    hp: int
    ap: int = 2
    cooldown: int = 0
    guard: bool = False
    reaction: bool = False
    suppressed: bool = False
    kills: int = 0
    facing: int = 0

    def face(self, position):
        dx, dy = position[0] - self.x, position[1] - self.y
        if dx or dy:
            self.facing = round(degrees(atan2(dy, dx))) % 360

    @property
    def pos(self):
        return self.x, self.y

    @property
    def spec(self):
        return CLASSES[self.role]

    @property
    def alive(self):
        return self.hp > 0


@dataclass
class Battle:
    scenario: str = "foundry"
    difficulty: str = "normal"
    mode: str = "command"
    round: int = 1
    phase: str = "player"
    score: dict = field(default_factory=lambda: {"blue": 0, "red": 0})
    points: list = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    events: list = field(default_factory=list)
    winner: str | None = None
    reason: str = ""
    serial: int = 0
    revision: int = 0
    actions: list = field(default_factory=list)

    def __post_init__(self):
        if (
            self.scenario not in SCENARIOS
            or self.difficulty not in ("easy", "normal", "hard")
            or self.mode not in ("command", "observe")
        ):
            raise ValueError("Неизвестные настройки операции")
        if not self.units:
            names = {
                "blue": ["Вектор", "Призрак", "Пульс", "Бастион"],
                "red": ["Шрам", "Сокол", "Искра", "Гром"],
            }
            for team in ("blue", "red"):
                for i, role in enumerate(CLASSES):
                    self.units.append(
                        Unit(
                            f"{team[0]}{i + 1}",
                            names[team][i],
                            role,
                            team,
                            1 if team == "blue" else 14,
                            [2, 4, 6, 8][i],
                            CLASSES[role]["hp"],
                            2 if team == "blue" else 0,
                            facing=0 if team == "blue" else 180,
                        )
                    )
        if not self.points:
            self.points = [
                {"id": name, "x": p[0], "y": p[1], "owner": None, "contested": False}
                for name, p in zip("ABC", SCENARIOS[self.scenario]["points"])
            ]
        if not self.events:
            self.log(
                "system",
                "Операция началась. Контролируйте узлы A, B и C: каждый приносит 5 очков за раунд.",
            )

    @property
    def walls(self):
        return TERRAIN[self.scenario]["walls"]

    @property
    def cover(self):
        return TERRAIN[self.scenario]["cover"]

    def unit(self, uid):
        return next((u for u in self.units if u.id == uid and u.alive), None)

    def living(self, team=None):
        return [u for u in self.units if u.alive and (team is None or u.team == team)]

    def log(self, kind, text, **data):
        self.serial += 1
        self.events.append(
            {"id": self.serial, "round": self.round, "kind": kind, "text": text, **data}
        )
        self.events = self.events[-160:]

    def line_of_sight(self, a, b):
        # Supercover traversal: walls at a crossed corner also block a shot.
        return clear_line(self.scenario, tuple(a), tuple(b))

    def reachable(self, u):
        blocked = self.walls | {v.pos for v in self.living() if v.id != u.id}
        paths = {u.pos: []}
        queue = deque([u.pos])
        while queue:
            pos = queue.popleft()
            if len(paths[pos]) >= u.spec["move"]:
                continue
            for dx, dy in ((1, 0), (0, 1), (-1, 0), (0, -1)):
                p = pos[0] + dx, pos[1] + dy
                if 0 <= p[0] < WIDTH and 0 <= p[1] < HEIGHT and p not in blocked and p not in paths:
                    paths[p] = paths[pos] + [p]
                    queue.append(p)
        del paths[u.pos]
        return paths

    def damage(self, target, amount, ignore_cover=False):
        return max(
            1,
            amount
            - (5 if target.pos in self.cover and not ignore_cover else 0)
            - (7 if target.guard else 0),
        )

    def legal_actions(self, u):
        if not u or not u.alive or u.ap <= 0 or self.phase == "finished":
            return []
        actions = [{"type": "move", "x": x, "y": y, "cost": 1} for x, y in self.reachable(u)]
        enemies = [v for v in self.living() if v.team != u.team]
        for v in enemies:
            if distance(u.pos, v.pos) <= u.spec["range"] and self.line_of_sight(u.pos, v.pos):
                actions.append(
                    {
                        "type": "attack",
                        "target": v.id,
                        "cost": 1,
                        "damage": self.damage(v, u.spec["damage"]),
                    }
                )
                if u.cooldown == 0 and u.role == "ranger" and u.ap >= 2:
                    actions.append(
                        {
                            "type": "skill",
                            "target": v.id,
                            "cost": 2,
                            "damage": self.damage(v, 35, True),
                        }
                    )
                if u.cooldown == 0 and u.role == "heavy":
                    actions.append(
                        {"type": "skill", "target": v.id, "cost": 1, "damage": self.damage(v, 18)}
                    )
        if u.cooldown == 0 and u.role == "medic":
            for v in self.living(u.team):
                if (
                    v.hp < v.spec["hp"]
                    and distance(u.pos, v.pos) <= 3
                    and self.line_of_sight(u.pos, v.pos)
                ):
                    actions.append(
                        {
                            "type": "skill",
                            "target": v.id,
                            "cost": 1,
                            "heal": min(28, v.spec["hp"] - v.hp),
                        }
                    )
        if u.cooldown == 0 and u.role == "assault":
            candidates = {
                (v.x + dx, v.y + dy)
                for v in enemies
                for dx, dy in ((0, 0), (1, 0), (-1, 0), (0, 1), (0, -1))
            }
            for pos in sorted(candidates):
                if (
                    valid_cell(pos)
                    and pos not in self.walls
                    and distance(u.pos, pos) <= 4
                    and self.line_of_sight(u.pos, pos)
                ):
                    victims = [v for v in enemies if distance(pos, v.pos) <= 1]
                    actions.append(
                        {
                            "type": "skill",
                            "x": pos[0],
                            "y": pos[1],
                            "cost": 1,
                            "damage": 24,
                            "targets": [v.id for v in victims],
                            "hits": {v.id: self.damage(v, 24, True) for v in victims},
                        }
                    )
        actions.append({"type": "guard", "cost": u.ap})
        return actions

    def apply(self, uid, request, team=None):
        if self.phase == "finished":
            raise ValueError("Операция уже завершена")
        u = self.unit(uid)
        if not u or (team and u.team != team):
            raise ValueError("Боец недоступен")
        expected = "blue" if self.phase == "player" else "red"
        if u.team != expected:
            raise ValueError("Сейчас ход другого отряда")
        if not isinstance(request, dict):
            raise ValueError("Некорректное действие")
        # Only identity fields are accepted; damage, cost and paths are server-owned.
        identity = {k: request[k] for k in ("type", "target", "x", "y") if k in request}
        for k in ("x", "y"):
            if k in identity and type(identity[k]) is not int:
                raise ValueError("Координаты должны быть целыми числами")
        legal = next(
            (
                a
                for a in self.legal_actions(u)
                if {k: a[k] for k in ("type", "target", "x", "y") if k in a} == identity
            ),
            None,
        )
        if legal is None:
            raise ValueError("Действие недоступно: проверьте ОД, дистанцию и линию огня")
        self.actions.append({"round": self.round, "team": u.team, "unit": uid, "action": identity})
        u.ap -= legal["cost"]
        kind = legal["type"]
        if kind != "guard":
            u.guard = u.reaction = False
        if kind == "move":
            start = u.pos
            path = self.reachable(u)[(legal["x"], legal["y"])]
            # Reserve the movement event before reactions; finalize its actual end below.
            self.log("move", "", team=u.team, unit=uid, start=start, end=start, path=[])
            movement = self.events[-1]
            actual_path = []
            for pos in path:
                u.face(pos)
                u.x, u.y = pos
                actual_path.append(pos)
                for defender in self.living():
                    if (
                        defender.team != u.team
                        and defender.reaction
                        and distance(defender.pos, pos) <= defender.spec["range"]
                        and self.line_of_sight(defender.pos, pos)
                    ):
                        defender.reaction = False
                        self.hit(
                            defender, u, self.damage(u, defender.spec["damage"]), "Ответный огонь"
                        )
                        if not u.alive:
                            break
                if not u.alive:
                    break
            movement.update(
                text=f"{u.name} {'движение прервано' if not u.alive else 'сменил позицию'} → {u.x + 1}:{u.y + 1}.",
                end=u.pos,
                path=actual_path,
            )
        elif kind == "guard":
            u.guard = u.reaction = True
            self.log(
                "guard",
                f"{u.name} прикрывает сектор: −7 входящего урона и один ответный выстрел при движении врага.",
                team=u.team,
                unit=uid,
            )
        elif kind == "attack":
            self.hit(u, self.unit(legal["target"]), legal["damage"], "Огонь")
        elif kind == "skill":
            u.cooldown = 3  # 2 own turns unavailable; decremented at turn start.
            if u.role == "medic":
                target = self.unit(legal["target"])
                u.face(target.pos)
                target.hp += legal["heal"]
                self.log(
                    "heal",
                    f"{u.name} → {target.name}: +{legal['heal']} здоровья.",
                    team=u.team,
                    unit=uid,
                    target=target.id,
                    end=target.pos,
                    amount=legal["heal"],
                )
            elif u.role == "assault":
                u.face((legal["x"], legal["y"]))
                self.log(
                    "grenade",
                    f"{u.name} бросил гранату. Поражено целей: {len(legal['targets'])}.",
                    team=u.team,
                    unit=uid,
                    start=u.pos,
                    end=(legal["x"], legal["y"]),
                )
                for vid in legal["targets"]:
                    target = self.unit(vid)
                    if target:
                        self.hit(u, target, self.damage(target, 24, True), "Граната")
            else:
                target = self.unit(legal["target"])
                if u.role == "heavy":
                    target.suppressed = True
                self.hit(u, target, legal["damage"], u.spec["skill"])
        self.revision += 1
        self.update_points(False)
        self.check_victory()
        return legal

    def hit(self, shooter, target, damage, label):
        if label != "Граната":
            shooter.face(target.pos)
        target.hp = max(0, target.hp - damage)
        self.log(
            "attack",
            f"{shooter.name} → {target.name}: {label.lower()}, −{damage} HP.",
            team=shooter.team,
            unit=shooter.id,
            target=target.id,
            start=shooter.pos,
            end=target.pos,
            amount=damage,
        )
        if not target.alive:
            shooter.kills += 1
            target.ap = 0
            target.guard = target.reaction = False
            target.suppressed = False
            self.log(
                "death",
                f"{target.name} выбыл из боя.",
                team=target.team,
                unit=target.id,
                end=target.pos,
            )

    def update_points(self, scoring):
        for p in self.points:
            teams = {u.team for u in self.living() if distance(u.pos, (p["x"], p["y"])) <= 1}
            p["contested"] = len(teams) > 1
            if len(teams) == 1:
                owner = next(iter(teams))
                if p["owner"] != owner:
                    p["owner"] = owner
                    self.log(
                        "capture",
                        f"Узел {p['id']} захвачен {'вашим отрядом' if owner == 'blue' else 'противником'}.",
                        team=owner,
                        point=p["id"],
                    )
            if scoring and p["owner"] and not p["contested"]:
                self.score[p["owner"]] += 5
        if scoring:
            self.log(
                "score",
                f"Итог раунда: {self.score['blue']} : {self.score['red']}. Спорные узлы очков не дают.",
            )

    def start_turn(self, team):
        self.phase = "player" if team == "blue" else "enemy"
        for u in self.living(team):
            u.ap = 1 if u.suppressed else 2
            u.suppressed = False
            u.cooldown = max(0, u.cooldown - 1)
            u.guard = u.reaction = False
        self.revision += 1

    def end_player_turn(self):
        if self.phase != "player":
            raise ValueError("Дождитесь своего хода")
        for u in self.living("blue"):
            u.ap = 0
        self.start_turn("red")
        self.log("turn", "Ход противника.")

    def end_enemy_turn(self):
        if self.phase == "finished":
            return
        if self.phase != "enemy":
            raise ValueError("Сейчас не ход противника")
        for u in self.living("red"):
            u.ap = 0
        self.update_points(True)
        self.check_victory(end_round=True)
        if self.phase != "finished":
            self.round += 1
            self.start_turn("blue")
            self.log("turn", f"Раунд {self.round}. Ваш отряд готов к действию.")

    def check_victory(self, end_round=False):
        if self.phase == "finished":
            return
        blue, red = self.living("blue"), self.living("red")
        winner, reason = None, ""
        if not blue or not red:
            winner = "blue" if blue else "red" if red else "draw"
            reason = {
                "blue": "Отряд противника выведен из боя.",
                "red": "Ваш отряд выведен из боя.",
                "draw": "Оба отряда выведены из боя.",
            }[winner]
        elif end_round and (max(self.score.values()) >= POINTS_TO_WIN or self.round >= ROUND_LIMIT):
            if self.score["blue"] != self.score["red"]:
                winner = max(self.score, key=self.score.get)
            else:
                bhp, rhp = sum(u.hp for u in blue), sum(u.hp for u in red)
                winner = "blue" if bhp > rhp else "red" if rhp > bhp else "draw"
            reason = (
                "Достигнут предел очков."
                if max(self.score.values()) >= POINTS_TO_WIN
                else "Лимит раундов. При равном счёте решает здоровье отряда."
            )
        if winner:
            self.winner, self.reason, self.phase = winner, reason, "finished"
            self.log(
                "victory",
                {
                    "blue": "Победа вашего отряда.",
                    "red": "Операция проиграна.",
                    "draw": "Операция завершилась вничью.",
                }[winner]
                + " "
                + reason,
            )

    def snapshot(self):
        return {
            "scenario": self.scenario,
            "scenario_info": {
                k: SCENARIOS[self.scenario][k] for k in ("name", "subtitle", "brief")
            },
            "difficulty": self.difficulty,
            "mode": self.mode,
            "width": WIDTH,
            "height": HEIGHT,
            "round": self.round,
            "round_limit": ROUND_LIMIT,
            "phase": self.phase,
            "score": self.score.copy(),
            "score_goal": POINTS_TO_WIN,
            "points": deepcopy(self.points),
            "walls": sorted(self.walls),
            "cover": sorted(self.cover),
            "units": [
                {**asdict(u), **u.spec, "max_hp": u.spec["hp"], "hp": u.hp} for u in self.units
            ],
            "events": deepcopy(self.events),
            "winner": self.winner,
            "reason": self.reason,
            "revision": self.revision,
            "legal": {u.id: self.legal_actions(u) for u in self.living("blue")}
            if self.phase == "player"
            else {},
        }

    def save(self):
        return {"version": 1, "battle": asdict(self)}

    @classmethod
    def restore(cls, data):
        try:
            return cls._restore(data)
        except (TypeError, KeyError, IndexError, AttributeError):
            raise ValueError("Сохранение содержит повреждённые данные") from None

    @classmethod
    def _restore(cls, data):
        if (
            not isinstance(data, dict)
            or type(data.get("version")) is not int
            or data.get("version") != 1
            or not isinstance(data.get("battle"), dict)
        ):
            raise ValueError("Неизвестный формат сохранения")
        d = deepcopy(data["battle"])
        if set(d) != set(cls.__dataclass_fields__) or d.get("phase") not in ("player", "finished"):
            raise ValueError("Сохранение неполное или создано во время хода противника")
        if (
            not isinstance(d["scenario"], str)
            or d["scenario"] not in SCENARIOS
            or d["difficulty"] not in ("easy", "normal", "hard")
            or d["mode"] not in ("command", "observe")
        ):
            raise ValueError("Некорректные настройки операции")
        if (
            type(d["round"]) is not int
            or not 1 <= d["round"] <= ROUND_LIMIT
            or type(d["revision"]) is not int
            or d["revision"] < 0
        ):
            raise ValueError("Некорректный раунд")
        if not isinstance(d["units"], list) or len(d["units"]) != 8:
            raise ValueError("Некорректный состав отрядов")
        units = []
        for raw in d["units"]:
            # Version 1 saves made before facing was introduced remain compatible.
            if isinstance(raw, dict) and "facing" not in raw:
                raw["facing"] = 180 if raw.get("team") == "red" else 0
            if not isinstance(raw, dict) or set(raw) != set(Unit.__dataclass_fields__):
                raise ValueError("Некорректные поля бойца")
            u = Unit(**raw)
            if type(u.facing) is not int or not 0 <= u.facing < 360:
                raise ValueError("Некорректное направление бойца")
            if (
                not isinstance(u.id, str)
                or not isinstance(u.role, str)
                or u.role not in CLASSES
                or u.team not in ("blue", "red")
                or not isinstance(u.name, str)
                or not 1 <= len(u.name) <= 40
            ):
                raise ValueError("Некорректный боец")
            if any(type(v) is not int for v in (u.x, u.y, u.hp, u.ap, u.cooldown, u.kills)) or not (
                0 <= u.x < WIDTH
                and 0 <= u.y < HEIGHT
                and 0 <= u.hp <= u.spec["hp"]
                and 0 <= u.ap <= 2
                and 0 <= u.cooldown <= 3
                and u.kills >= 0
            ):
                raise ValueError("Некорректные параметры бойца")
            if any(type(v) is not bool for v in (u.guard, u.reaction, u.suppressed)):
                raise ValueError("Некорректное состояние бойца")
            units.append(u)
        if {u.id for u in units} != {f"{t}{i}" for t in "br" for i in range(1, 5)} or any(
            u.id[0] != u.team[0] for u in units
        ):
            raise ValueError("Некорректные идентификаторы")
        if any(
            u.role != list(CLASSES)[int(u.id[1]) - 1]
            or (not u.alive and (u.ap or u.guard or u.reaction))
            or (u.reaction and not u.guard)
            or (u.team == "red" and u.ap and d["phase"] == "player")
            for u in units
        ):
            raise ValueError("Состояние отряда несовместимо с фазой боя")
        if (
            not isinstance(d["score"], dict)
            or d["score"].keys() != {"blue", "red"}
            or any(type(v) is not int or not 0 <= v <= 300 for v in d["score"].values())
        ):
            raise ValueError("Некорректный счёт")
        if (
            not isinstance(d["events"], list)
            or len(d["events"]) > 160
            or not isinstance(d["actions"], list)
            or len(d["actions"]) > 400
        ):
            raise ValueError("Некорректный журнал")
        if (
            type(d["serial"]) is not int
            or d["serial"] < 0
            or any(
                not isinstance(e, dict)
                or type(e.get("id")) is not int
                or not isinstance(e.get("text"), str)
                or len(e["text"]) > 500
                for e in d["events"]
            )
        ):
            raise ValueError("Некорректные события")
        ids = {u.id for u in units}
        event_ids = []
        for event in d["events"]:
            if (
                event.get("kind")
                not in (
                    "system",
                    "move",
                    "guard",
                    "attack",
                    "heal",
                    "grenade",
                    "death",
                    "capture",
                    "score",
                    "turn",
                    "plan",
                    "victory",
                )
                or type(event.get("round")) is not int
                or not 1 <= event["round"] <= d["round"]
                or not 1 <= event["id"] <= d["serial"]
            ):
                raise ValueError("Некорректный тип или номер события")
            if (
                "team" in event
                and event["team"] not in ("blue", "red")
                or any(k in event and event[k] not in ids for k in ("unit", "target"))
            ):
                raise ValueError("Некорректный участник события")
            if (
                any(k in event and not valid_cell(event[k]) for k in ("start", "end"))
                or "path" in event
                and (
                    not isinstance(event["path"], list)
                    or len(event["path"]) > 4
                    or not all(valid_cell(p) for p in event["path"])
                )
            ):
                raise ValueError("Некорректные координаты события")
            if (
                "amount" in event
                and (type(event["amount"]) is not int or not 0 <= event["amount"] <= 115)
                or "point" in event
                and event["point"] not in ("A", "B", "C")
            ):
                raise ValueError("Некорректные данные события")
            event_ids.append(event["id"])
        if event_ids != sorted(set(event_ids)) or event_ids and event_ids[-1] != d["serial"]:
            raise ValueError("Журнал событий не упорядочен")
        for entry in d["actions"]:
            if (
                not isinstance(entry, dict)
                or set(entry) != {"round", "team", "unit", "action"}
                or type(entry["round"]) is not int
                or not 1 <= entry["round"] <= d["round"]
                or entry["team"] not in ("blue", "red")
                or not isinstance(entry["unit"], str)
                or entry["unit"] not in ids
                or entry["unit"][0] != entry["team"][0]
            ):
                raise ValueError("Некорректная запись действия")
            action = entry["action"]
            if (
                not isinstance(action, dict)
                or action.get("type") not in ("move", "attack", "skill", "guard")
                or set(action) - {"type", "target", "x", "y"}
                or "target" in action
                and action["target"] not in ids
                or ("x" in action or "y" in action)
                and not valid_cell((action.get("x"), action.get("y")))
            ):
                raise ValueError("Некорректное действие в журнале")
        if (
            d["winner"] not in (None, "blue", "red", "draw")
            or (d["phase"] == "finished") != (d["winner"] is not None)
            or not isinstance(d["reason"], str)
        ):
            raise ValueError("Некорректный итог операции")
        if d["phase"] == "player" and (
            not any(u.alive and u.team == "blue" for u in units)
            or not any(u.alive and u.team == "red" for u in units)
        ):
            raise ValueError("Незавершённый бой без живого отряда")
        if not isinstance(d["points"], list) or len(d["points"]) != 3:
            raise ValueError("Некорректные узлы")
        d["units"] = units
        b = cls(**d)
        expected = [(p[0], p[1]) for p in SCENARIOS[b.scenario]["points"]]
        if (
            not isinstance(b.points, list)
            or len(b.points) != 3
            or any(
                not isinstance(p, dict)
                or p.get("id") != label
                or (p.get("x"), p.get("y")) != pos
                or p.get("owner") not in (None, "blue", "red")
                or type(p.get("contested")) is not bool
                for p, label, pos in zip(b.points, "ABC", expected)
            )
        ):
            raise ValueError("Некорректные узлы")
        positions = [u.pos for u in b.living()]
        if len(set(positions)) != len(positions) or any(pos in b.walls for pos in positions):
            raise ValueError("Бойцы находятся на недопустимых позициях")
        return b
