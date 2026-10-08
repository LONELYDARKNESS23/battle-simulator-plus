# RIFT 1.1 — 2026-10-08

Context recovered from chats «Улучши копию игры» and «Выполни задачу со скриншота».
Continue battle-simulator-plus; original untouched, no license added.

Implemented persisted facing, old-save migration, attack/reaction/healing/grenade headings,
actual-path movement animation, generated local raster assets, class equipment,
directional overlays, larger map, next ready unit, simplified briefing.
Windowless Windows launcher and root shortcut; session reuse, port exclusivity,
explicit in-game shutdown. Standard Python only.

Validation: 56 Python tests pass (including nine complete matches); six JS tests pass;
Ruff lint/format and node syntax checks pass.
UI checked at 1440x1000 and 390x844: start/resume, upward movement + heading,
next unit, large map (1058px canvas), no horizontal overflow, no console errors,
shutdown confirmation and closed state. Tests used isolated .local/visual-check profile.
Launcher tested from Launch.ps1 and with separate-process reuse/shutdown tests.
Main profile saves/config preserved. Latest launcher left on loopback for user.

Generated art provenance and full prompts: docs/ART.md.
Release: dist/rift-battle-simulator-1.1.0.zip, with SHA-256 sidecar.
