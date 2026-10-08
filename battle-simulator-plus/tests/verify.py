"""Write a reproducible local verification record without accessing a real model."""

import contextlib
import hashlib
import io
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
out = io.StringIO()
suite = unittest.defaultTestLoader.discover(str(ROOT / "tests"), pattern="test_*.py")
with contextlib.redirect_stdout(out):
    result = unittest.TextTestRunner(stream=out, verbosity=2).run(suite)
evidence = ROOT / "evidence"
evidence.mkdir(exist_ok=True)
(evidence / "tests.txt").write_text(out.getvalue(), encoding="utf-8")
sources = [
    "oop_mini_game.sln",
    "oop_mini_game/oop_mini_game.py",
    "oop_mini_game/Unit.py",
    "oop_mini_game/Point2D.py",
    "oop_mini_game/oop_mini_game.pyproj",
]
hashes = []
for name in sources:
    source = ROOT.parent / name
    original = ROOT / "original" / name
    if source.exists() and original.exists():
        a = hashlib.sha256(source.read_bytes()).hexdigest()
        b = hashlib.sha256(original.read_bytes()).hexdigest()
        hashes.append({"file": name, "source_sha256": a, "copy_sha256": b, "equal": a == b})
report = {
    "python": sys.version.split()[0],
    "tests": result.testsRun,
    "successful": result.wasSuccessful(),
    "failures": len(result.failures),
    "errors": len(result.errors),
    "original_files": hashes,
}
(evidence / "verification.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(out.getvalue())
print(json.dumps(report, indent=2))
raise SystemExit(0 if result.wasSuccessful() and all(h["equal"] for h in hashes) else 1)
