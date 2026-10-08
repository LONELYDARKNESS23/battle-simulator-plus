"""Bounded JSON reads and atomic writes shared by config and save slots."""

import json
import tempfile
from pathlib import Path


def read_json(path, limit=1_048_576):
    with Path(path).open("rb") as source:
        raw = source.read(limit + 1)
    if len(raw) > limit:
        raise ValueError("Файл JSON слишком большой")
    try:
        return json.loads(raw.decode("utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("Файл содержит некорректный JSON") from None


def atomic_json(path, value):
    path = Path(path)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.stem}.",
            suffix=".tmp",
            delete=False,
        ) as output:
            temporary = Path(output.name)
            json.dump(value, output, ensure_ascii=False, indent=2, allow_nan=False)
            output.write("\n")
        temporary.replace(path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
