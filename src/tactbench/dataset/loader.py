"""Reading and writing dataset splits as JSONL."""

from __future__ import annotations

import json
from pathlib import Path

from ..schema import Item

DATA_ROOT = Path(__file__).resolve().parents[3] / "data"


def write_jsonl(items: list[Item], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as f:
        for item in items:
            f.write(item.model_dump_json() + "\n")


def read_jsonl(path: Path) -> list[Item]:
    items: list[Item] = []
    with path.open() as f:
        for line in f:
            line = line.strip()
            if line:
                items.append(Item.model_validate(json.loads(line)))
    return items


def split_path(version: str, split: str) -> Path:
    return DATA_ROOT / version / f"{split}.jsonl"


def load(version: str = "v1", split: str = "dev") -> list[Item]:
    path = split_path(version, split)
    if not path.exists():
        raise FileNotFoundError(
            f"No dataset at {path}. Run `tactbench build` to generate it."
        )
    return read_jsonl(path)
