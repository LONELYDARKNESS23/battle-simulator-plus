"""Windowless, single-instance launcher. Uses only the Python standard library."""

import argparse
import json
import os
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

from game.storage import atomic_json
from start import ROOT, GameServer, Session


def acquire_lock(path):
    handle = path.open("a+b")
    if path.stat().st_size == 0:
        handle.write(b"0")
        handle.flush()
    handle.seek(0)
    try:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None
    return handle


def existing_url(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        port = data["port"]
        if type(port) is not int or not 1 <= port <= 65535:
            return None
        url = f"http://127.0.0.1:{port}"
        with urllib.request.urlopen(url + "/api/state", timeout=0.5) as response:
            state = json.load(response)
        return url if state.get("session_id") == data["session_id"] else None
    except (OSError, ValueError, KeyError, TypeError):
        return None


def launch(data_dir=ROOT, open_browser=True):
    data_dir = Path(data_dir).resolve()
    local = data_dir / ".local"
    local.mkdir(parents=True, exist_ok=True)
    endpoint = local / "launcher.json"
    handle = acquire_lock(local / "launcher.lock")
    if handle is None:
        for _ in range(50):
            url = existing_url(endpoint)
            if url:
                if open_browser:
                    webbrowser.open(url)
                return url
            time.sleep(0.1)
        raise RuntimeError(
            "Игра запускается или завершает работу. Повторите запуск через несколько секунд."
        )
    server = None
    try:
        session = Session(data_dir)
        for port in range(8765, 8785):
            try:
                server = GameServer(("127.0.0.1", port), session)
                break
            except OSError:
                continue
        if server is None:
            raise RuntimeError("Порты 8765–8784 заняты. Освободите один из них и повторите запуск.")
        atomic_json(
            endpoint, {"port": server.server_port, "session_id": session.state()["session_id"]}
        )
        url = f"http://127.0.0.1:{server.server_port}"
        if open_browser:
            threading.Timer(0.4, lambda: webbrowser.open(url)).start()
        server.serve_forever(poll_interval=0.2)
        return url
    finally:
        if server:
            server.server_close()
        endpoint.unlink(missing_ok=True)
        handle.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    try:
        launch(args.data_dir, not args.no_browser)
    except Exception as error:
        if os.name == "nt":
            import ctypes

            ctypes.windll.user32.MessageBoxW(0, str(error), "RIFT — ошибка запуска", 16)
        else:
            raise
