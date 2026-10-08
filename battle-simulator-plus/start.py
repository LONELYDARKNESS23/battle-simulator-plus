"""Run with Python 3.10+; no third-party packages needed."""

from __future__ import annotations

import argparse
import json
import socket
import threading
import time
import urllib.parse
import uuid
import webbrowser
from copy import deepcopy
from dataclasses import asdict
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from game.commanders import (
    BuiltinCommander,
    ProviderConfig,
    choose_action,
    execute_plan,
    get_commander,
    request_json,
    validate_key,
)
from game.engine import SCENARIOS, Battle
from game.storage import atomic_json, read_json

ROOT = Path(__file__).resolve().parent


class StaleStateError(ValueError):
    """A command belongs to an earlier view of the shared game."""


class Session:
    def __init__(self, root=ROOT):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.RLock()
        self.battle = Battle()
        self.config = ProviderConfig()
        self.config_warning = ""
        try:
            if (self.root / "config.json").exists():
                self.config = ProviderConfig.validate(read_json(self.root / "config.json", 16000))
        except (ValueError, TypeError, OSError):
            self.config_warning = "Не удалось прочитать config.json. Включён встроенный командир."
        self.session_key = ""
        self.generation = 0
        self.undo = []
        self.busy_since = None
        self.inflight = False
        self.ai = {
            "source": "builtin",
            "latency": 0,
            "fallback": False,
            "message": self.config_warning or "Командир готов",
            "orders": [],
            "requests": 0,
            "failures": 0,
        }
        self.session_id = uuid.uuid4().hex
        self.state_revision = 0
        self._view_key = None
        self._core_key = None
        self._core = None

    def state(self, since=None, session_id=None):
        with self.lock:
            core_key = (id(self.battle), self.battle.revision, self.battle.serial, self.generation)
            has_save = any(
                (self.root / name).exists() for name in ("savegame.json", "autosave.json")
            )
            view_key = (
                core_key,
                self.generation,
                len(self.undo),
                has_save,
                self.inflight,
                json.dumps(self.ai, sort_keys=True),
                json.dumps(asdict(self.config), sort_keys=True),
            )
            if view_key != self._view_key:
                self.state_revision += 1
                self._view_key = view_key
            ai = {
                **deepcopy(self.ai),
                "configured": self.config.provider,
                "model": self.config.model,
                "busy_seconds": round(time.monotonic() - self.busy_since, 1)
                if self.busy_since
                else 0,
                "can_request": not self.inflight,
            }
            envelope = {
                "session_id": self.session_id,
                "state_revision": self.state_revision,
                "battle_id": self.generation,
                "serial": self.battle.serial,
                "ai": ai,
            }
            if since == self.state_revision and session_id == self.session_id:
                return {**envelope, "unchanged": True}
            if core_key != self._core_key:
                self._core = self.battle.snapshot()
                self._core_key = core_key
            return {
                **deepcopy(self._core),
                **envelope,
                "can_undo": bool(self.undo) and self.battle.phase in ("player", "finished"),
                "has_save": has_save,
                "scenarios": [
                    {"id": k, "name": v["name"], "brief": v["brief"]} for k, v in SCENARIOS.items()
                ],
            }

    def autosave(self):
        if self.battle.phase in ("player", "finished"):
            try:
                atomic_json(self.root / "autosave.json", self.battle.save())
            except OSError:
                self.battle.log(
                    "system", "Не удалось записать автосохранение. Проверьте права папки."
                )

    def launch_enemy(self, use_builtin=False):
        with self.lock:
            self.battle.end_player_turn()
            self.undo.clear()
            self.generation += 1
            token = self.generation
            snapshot = deepcopy(self.battle)
            config = deepcopy(self.config)
            key = self.session_key
            # Never start another network request while an abandoned one is still running.
            builtin = use_builtin or self.inflight or config.provider == "builtin"
            if not builtin:
                self.inflight = True
            self.busy_since = time.monotonic()
            self.ai["message"] = (
                "Противник выбирает план" if not builtin else "Противник выполняет план"
            )

        def work(initial=snapshot):
            snapshot = initial
            started = time.monotonic()
            fallback = builtin and config.provider != "builtin"
            message = (
                "Предыдущий запрос ещё завершается; этот ход выполнил встроенный ИИ"
                if fallback
                else "План выполнен"
            )
            source = "builtin" if builtin else config.provider
            try:
                orders = (BuiltinCommander() if builtin else get_commander(config, key)).plan(
                    snapshot, "red"
                )
            except Exception as e:
                fallback, source = True, "builtin"
                message = str(e) if isinstance(e, ValueError) else "Ошибка подключения модели"
                orders = BuiltinCommander().plan(snapshot, "red")
            # Resolve into a private battle first. A failure cannot leave a partial turn.
            original = deepcopy(snapshot)
            try:
                self.resolve_enemy(snapshot, orders)
            except Exception:
                snapshot = deepcopy(original)
                orders = BuiltinCommander().plan(snapshot, "red")
                fallback, source, message = (
                    True,
                    "builtin",
                    "Ошибка исполнения плана; ход завершён резервным ИИ",
                )
                try:
                    self.resolve_enemy(snapshot, orders)
                except Exception:
                    snapshot = deepcopy(original)
                    for u in snapshot.living("red"):
                        u.ap = 0
                        u.guard = u.reaction = True
                    snapshot.log(
                        "system",
                        "Ошибка тактики: противник удерживает позиции. Можно продолжать бой.",
                    )
                    snapshot.end_enemy_turn()
            with self.lock:
                if not builtin:
                    self.inflight = False
                if token != self.generation:
                    return
                self.battle = snapshot
                self.ai.update(
                    source=source,
                    latency=round(time.monotonic() - started, 2),
                    fallback=fallback,
                    message=message,
                    orders=orders,
                )
                self.ai["requests"] += int(not builtin)
                self.ai["failures"] += int(fallback)
                if fallback:
                    self.battle.log("system", message + ". Использован резервный командир.")
                self.busy_since = None
                self.autosave()

        threading.Thread(target=work, name=f"enemy-turn-{token}", daemon=True).start()

    @staticmethod
    def resolve_enemy(battle, orders):
        intentions = {
            "capture": "захват",
            "fight": "атака",
            "support": "поддержка",
            "hold": "оборона",
        }
        roster = {u.id: u for u in battle.units}
        targets = "; ".join(
            f"{roster[o['unit']].name}: {intentions[o['intent']]} {roster[o['target']].name if o['target'] in roster else o['target']}"
            for o in orders
        )
        battle.log("plan", "План противника: " + targets + ".", team="red")
        execute_plan(battle, "red", orders)
        battle.end_enemy_turn()

    def fallback_now(self):
        with self.lock:
            if self.battle.phase != "enemy":
                raise ValueError("Противник сейчас не думает")
            self.generation += 1
            orders = BuiltinCommander().plan(self.battle, "red")
            resolved = deepcopy(self.battle)
            self.resolve_enemy(resolved, orders)
            self.battle = resolved
            self.busy_since = None
            self.ai.update(
                source="builtin",
                fallback=True,
                message="Этот ход выполнен встроенным командиром",
                orders=orders,
            )
            self.autosave()

    def mutate(self, route, body):
        with self.lock:
            if "expected_revision" in body:
                view = self.state()
                if (
                    body.get("expected_session") != self.session_id
                    or body["expected_revision"] != view["state_revision"]
                ):
                    raise StaleStateError(
                        "Поле боя изменилось. Состояние обновлено; повторите действие."
                    )
            b = self.battle
            if route == "/api/new":
                new = Battle(
                    scenario=body.get("scenario", "foundry"),
                    difficulty=body.get("difficulty", "normal"),
                    mode=body.get("mode", "command"),
                )
                self.generation += 1
                self.battle, self.undo, self.busy_since = new, [], None
                self.ai.update(orders=[], fallback=False, message="Новая операция готова")
                self.autosave()
            elif route == "/api/action":
                if b.phase != "player" or b.mode != "command":
                    raise ValueError(
                        "Дождитесь своего хода; в режиме наблюдения команды выполняются автоматически"
                    )
                previous = deepcopy(b)
                b.apply(body.get("unit"), body.get("action"), "blue")
                self.undo.append(previous)
                self.undo = self.undo[-8:]
                self.autosave()
            elif route == "/api/undo":
                if b.phase not in ("player", "finished") or not self.undo:
                    raise ValueError("Нет действия для отмены")
                revision = b.revision
                self.battle = self.undo.pop()
                self.battle.revision = revision + 1
                self.autosave()
            elif route == "/api/end-turn":
                self.launch_enemy()
            elif route == "/api/auto":
                if b.phase != "player":
                    raise ValueError("Дождитесь своего хода")
                self.undo.append(deepcopy(b))
                resolved = deepcopy(b)
                execute_plan(resolved, "blue", BuiltinCommander().plan(resolved, "blue"))
                self.battle = b = resolved
                if b.phase != "finished":
                    self.launch_enemy()
                else:
                    self.autosave()
            elif route == "/api/fallback":
                self.fallback_now()
            elif route == "/api/save":
                if b.phase not in ("player", "finished"):
                    raise ValueError("Сохранить можно после хода противника")
                atomic_json(self.root / "savegame.json", b.save())
            elif route == "/api/load":
                names = (
                    ("autosave.json", "savegame.json")
                    if body.get("slot") == "auto"
                    else ("savegame.json", "autosave.json")
                )
                path = next(
                    (self.root / name for name in names if (self.root / name).exists()),
                    self.root / names[0],
                )
                restored = Battle.restore(read_json(path))
                self.generation += 1
                self.battle, self.undo, self.busy_since = restored, [], None
                self.ai.update(orders=[], fallback=False, message="Сохранённая операция загружена")
            else:
                raise ValueError("Неизвестная команда")
        return self.state()


class GameServer(ThreadingHTTPServer):
    daemon_threads = True

    def server_bind(self):
        # Windows SO_REUSEADDR can silently bind two games to the same port.
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.allow_reuse_address = False
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()

    def __init__(self, address, session):
        super().__init__(address, Handler)
        self.session = session


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def do_HEAD(self):
        self.do_GET()

    def send_data(self, data, status=200, mime="application/json; charset=utf-8"):
        raw = (
            json.dumps(data, ensure_ascii=False).encode("utf-8")
            if mime.startswith("application/json")
            else data
        )
        self.send_response(status)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; frame-ancestors 'none'",
        )
        self.end_headers()
        try:
            if self.command != "HEAD":
                self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def trusted(self, mutation=False):
        host = self.headers.get("Host", "")
        if host not in (
            f"127.0.0.1:{self.server.server_port}",
            f"localhost:{self.server.server_port}",
        ):
            return False
        origin = self.headers.get("Origin")
        if origin and origin not in (
            f"http://127.0.0.1:{self.server.server_port}",
            f"http://localhost:{self.server.server_port}",
        ):
            return False
        return not mutation or self.headers.get("X-Battle-Client") == "1"

    def do_GET(self):
        if not self.trusted():
            self.send_data({"error": "Запрос должен исходить из локальной игры"}, 403)
            return
        route = urllib.parse.urlparse(self.path).path
        session = self.server.session
        try:
            if route == "/api/state":
                query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
                try:
                    since = int(query["since"][0]) if "since" in query else None
                except ValueError:
                    self.send_data({"error": "Некорректная версия состояния"}, 400)
                    return
                self.send_data(session.state(since, query.get("session", [None])[0]))
            elif route == "/api/config":
                self.send_data(
                    {
                        **asdict(session.config),
                        "has_key": bool(session.session_key),
                        "warning": session.config_warning,
                    }
                )
            elif route == "/api/export":
                with session.lock:
                    self.send_data(
                        {
                            "game": "RIFT",
                            "version": 1,
                            "provider": session.config.provider,
                            "model": session.config.model,
                            **session.battle.save(),
                        }
                    )
            else:
                files = {
                    "/": ("index.html", "text/html; charset=utf-8"),
                    "/style.css": ("style.css", "text/css; charset=utf-8"),
                    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
                    "/client-state.js": ("client-state.js", "text/javascript; charset=utf-8"),
                    "/battlefield-art.js": ("battlefield-art.js", "text/javascript; charset=utf-8"),
                    "/assets/ground.png": ("assets/ground.png", "image/png"),
                    "/assets/soldier.png": ("assets/soldier.png", "image/png"),
                    "/favicon.svg": ("favicon.svg", "image/svg+xml"),
                }
                if route not in files:
                    self.send_data({"error": "Не найдено"}, 404)
                    return
                name, mime = files[route]
                self.send_data((ROOT / "web" / name).read_bytes(), mime=mime)
        except Exception:
            self.send_data({"error": "Не удалось прочитать данные игры"}, 500)

    def do_POST(self):
        if not self.trusted(True):
            self.send_data({"error": "Запрос должен исходить из локальной игры"}, 403)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if not 0 < length <= 16000:
                raise ValueError("Некорректный размер запроса")
            body = json.loads(self.rfile.read(length))
            if not isinstance(body, dict):
                raise ValueError("Нужен JSON-объект")
            session = self.server.session
            route = urllib.parse.urlparse(self.path).path
            if route == "/api/shutdown":
                with session.lock:
                    if session.battle.phase == "enemy":
                        raise ValueError(
                            "Дождитесь окончания хода противника или завершите ожидание."
                        )
                    if body.get("expected_session") != session.session_id:
                        raise StaleStateError("Сеанс изменился. Обновите страницу.")
                self.send_data({"ok": True})
                threading.Thread(target=self.server.shutdown, daemon=True).start()
            elif route == "/api/config":
                config = ProviderConfig.validate(body)
                key = body.get("api_key", "")
                validate_key(key)
                if type(body.get("clear_key", False)) is not bool:
                    raise ValueError("Переключатель удаления ключа должен быть true/false")
                with session.lock:
                    atomic_json(session.root / "config.json", asdict(config))
                    session.config = config
                    session.config_warning = ""
                    if body.get("clear_key"):
                        session.session_key = ""
                    elif key:
                        session.session_key = key
                self.send_data({"ok": True, "has_key": bool(session.session_key), **asdict(config)})
            elif route == "/api/models":
                config = ProviderConfig.validate({**asdict(session.config), **body})
                if config.provider != "ollama":
                    raise ValueError("Список моделей доступен для Ollama")
                response = request_json(config.base_url + "/api/tags", timeout=5)
                if not isinstance(response.get("models"), list):
                    raise ValueError("Сервер вернул некорректный список моделей")
                self.send_data(
                    {
                        "models": [
                            m["name"]
                            for m in response.get("models", [])
                            if isinstance(m, dict) and isinstance(m.get("name"), str)
                        ]
                    }
                )
            elif route == "/api/test-model":
                config = ProviderConfig.validate(body) if body else deepcopy(session.config)
                key = body.get("api_key", "") or (
                    "" if body.get("clear_key") else session.session_key
                )
                validate_key(key)
                with session.lock:
                    if session.inflight:
                        raise ValueError("Дождитесь завершения предыдущего запроса к модели")
                    session.inflight = True
                    snapshot = (
                        deepcopy(session.battle) if session.battle.living("red") else Battle()
                    )
                started = time.monotonic()
                try:
                    orders = get_commander(config, key).plan(snapshot, "red")
                finally:
                    with session.lock:
                        session.inflight = False
                self.send_data(
                    {"ok": True, "latency": round(time.monotonic() - started, 2), "orders": orders}
                )
            elif route == "/api/advice":
                with session.lock:
                    uid = body.get("unit")
                    if (
                        session.battle.phase != "player"
                        or not session.battle.unit(uid)
                        or session.battle.unit(uid).team != "blue"
                    ):
                        raise ValueError("Выберите своего бойца в свой ход")
                    self.send_data({"action": choose_action(session.battle, uid)})
            else:
                self.send_data(session.mutate(route, body))
        except StaleStateError as e:
            self.send_data({"error": str(e)}, 409)
        except (ValueError, TypeError, KeyError, FileNotFoundError) as e:
            message = (
                str(e)
                if isinstance(e, ValueError)
                else "Не удалось прочитать сохранение или настройки"
            )
            self.send_data({"error": message}, 400)
        except OSError:
            self.send_data({"error": "Ошибка записи. Проверьте права папки игры."}, 500)
        except Exception:
            self.send_data({"error": "Не удалось выполнить действие"}, 500)


def main():
    parser = argparse.ArgumentParser(description="RIFT tactical battle simulator")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument(
        "--data-dir", type=Path, default=ROOT, help="Folder for local configuration and save slots"
    )
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("Порт должен быть в диапазоне 1–65535")
    session = Session(args.data_dir)
    server = None
    for port in range(args.port, min(args.port + 10, 65536)):
        try:
            server = GameServer(("127.0.0.1", port), session)
            break
        except OSError:
            continue
    if server is None:
        parser.exit(1, "Не удалось открыть порт игры. Укажите --port с другим номером.\n")
    url = f"http://127.0.0.1:{server.server_port}"
    print(
        f"RIFT / Battle Simulator Plus\n{url}\nKeep this window open. Ctrl+C to stop.", flush=True
    )
    if not args.no_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        print("\nGame server stopped.")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
