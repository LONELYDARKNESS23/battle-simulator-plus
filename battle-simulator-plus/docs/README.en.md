# RIFT — Tactical Battle Simulator

A local turn-based squad game with interchangeable AI commanders. Capture control points, use cover and class abilities, or watch two squads play automatically. The model gives squad intentions; the rules engine validates every action. There is no generated character chat.

## Play

Requires **Python 3.10+**. No third-party Python packages, Node, API key or model is needed to play.

- Windows: double-click `START_GAME.bat`, then click **В бой**. No console needs to stay open. Reopening the launcher reuses the running session; **Выйти → Закрыть игру** stops the server. Closing a browser tab alone does not stop it.
- Linux/macOS: `sh START_GAME.sh`, or `python3 start.py`.
- Command line: `python start.py --no-browser --port 8765`.

Open the printed local URL, normally http://127.0.0.1:8765. The server binds only to loopback. Keep the server running while playing.

## Rules and controls

Four units per team, two action points per unit. Move or shoot for one AP. An assault unit can throw a grenade, a ranger can use a two-AP precise shot, a medic can heal, and a heavy unit can suppress an enemy's next turn. Cover reduces incoming damage by 5. Guard ends the unit's actions, reduces damage by 7, and gives one reaction shot against a moving enemy. Walls block movement and fire.

Stand on or next to a control point to capture it. Each owned, uncontested point scores 5 after a full round. Reach 60 points or eliminate the enemy. At round 18 the higher score wins; remaining health breaks ties.

| Key | Action |
|---|---|
| 1–4 | Select a friendly unit |
| M / F / Q / G | Move / shoot / skill / guard |
| Space | End your turn |
| P | Pause/resume observer mode |
| Escape | Clear action selection |
| Arrows / Enter on the map | Select a cell / execute action |

The UI is currently in Russian. Advice previews an action without executing it. Autopilot executes the rest of your turn. Observer mode uses the built-in commander for your squad and the configured provider for the opposing squad.

## Connect another model

Open **Командир** in the top bar. Choose Ollama or a compatible Chat Completions API, enter a server base URL and exact model name, test, then save.

- Ollama example: `http://127.0.0.1:11434`, model `gemma4:e4b`.
- Compatible local API example: `http://127.0.0.1:1234/v1`. The adapter appends `/chat/completions`.
- Keys can be supplied in the UI for the process lifetime or through `BATTLE_API_KEY`. Keys are never saved or exported.
- Disable structured JSON if the server does not support JSON response mode. The returned plan must still follow the documented JSON contract.
- Unavailable or invalid model responses use the built-in fallback. Late responses cannot mutate a reset or cancelled operation.

Fresh checkouts use the built-in commander. `config.example.json` documents optional settings; local `config.json` is ignored by Git. Separate profiles: `python start.py --data-dir .local/profile-a --port 8800`.

## Develop

```sh
python -X utf8 -m unittest discover -s tests -v
npm run check
npm test
python tools/build_release.py
```

Node is optional for frontend checks; those tests have no npm dependencies. GitHub Actions is configured for Python tests on Windows/Linux and Python 3.10/3.12/3.14, lint, formatting and frontend lifecycle checks.

The release builder excludes local configuration, credentials, save slots, caches and audit logs. Manual saves and autosaves are separate. Battle exports are JSON logs for analysis, not animated replays.

See the [Russian manual](../README.md) and [contribution guide](../CONTRIBUTING.md). A project license has not been selected yet.
