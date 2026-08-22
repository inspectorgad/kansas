"""Validate, write, and version the published JSON.

Each run writes the current payload to data/<name>.json and, when the content
has actually changed, appends a timestamped snapshot to data/history/<stem>/.
The snapshots are what make the trend charts possible: they are the only record
of what the numbers looked like last week.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from config import DATA_DIR, HISTORY_DIR
from schemas import FILES, Payload


def now() -> datetime:
    return datetime.now(UTC)


def _serialize(payload: Payload) -> str:
    # by_alias + exclude_none keeps the served files small; sort_keys makes the
    # diff meaningful so we only snapshot real changes.
    return json.dumps(
        payload.model_dump(mode="json", by_alias=True, exclude_none=True),
        indent=2,
        sort_keys=True,
    )


def _content_without_timestamp(text: str) -> str:
    """Drop generated_at so a run that changed nothing is not counted as a change."""
    data = json.loads(text)
    data.pop("generated_at", None)
    return json.dumps(data, sort_keys=True)


def write(name: str, payload: Payload, data_dir: str | Path = DATA_DIR) -> bool:
    """Write one payload file. Returns True when its content changed.

    Raises if `name` is not part of the declared contract, or if the payload
    does not match the model registered for it.
    """
    if name not in FILES:
        raise KeyError(f"{name} is not part of the published contract: {sorted(FILES)}")
    expected = FILES[name]
    if not isinstance(payload, expected):
        raise TypeError(f"{name} expects {expected.__name__}, got {type(payload).__name__}")

    # Round-trip through the model to guarantee what we write validates.
    text = _serialize(expected.model_validate(payload.model_dump(mode="json")))

    root = Path(data_dir)
    root.mkdir(parents=True, exist_ok=True)
    target = root / name

    changed = True
    if target.exists():
        try:
            changed = _content_without_timestamp(target.read_text()) != _content_without_timestamp(text)
        except json.JSONDecodeError:
            changed = True

    target.write_text(text + "\n")

    if changed:
        # Microsecond precision keeps lexicographic filename order chronological
        # and stops two writes in the same second from clobbering a data point.
        stamp = payload.generated_at.strftime("%Y%m%dT%H%M%S_%fZ")
        snapshot_dir = root / HISTORY_DIR / Path(name).stem
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        snapshot = snapshot_dir / f"{stamp}.json"
        suffix = 2
        while snapshot.exists():
            snapshot = snapshot_dir / f"{stamp}~{suffix}.json"
            suffix += 1
        snapshot.write_text(text + "\n")

    return changed


def load_history(name: str, data_dir: str | Path = DATA_DIR) -> list[dict]:
    """Read every snapshot for a file, oldest first. Used to rebuild trend series."""
    snapshot_dir = Path(data_dir) / HISTORY_DIR / Path(name).stem
    if not snapshot_dir.is_dir():
        return []
    out = []
    for path in sorted(snapshot_dir.glob("*.json")):
        try:
            out.append(json.loads(path.read_text()))
        except json.JSONDecodeError:
            continue  # a truncated snapshot should not break the current run
    return out
