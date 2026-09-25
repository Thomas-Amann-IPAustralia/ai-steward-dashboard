"""Reading and writing the committed state files.

The JSON and text files in the repository are the pipeline's datastore, so
how they are read and written is shared by all three orchestrators rather
than re-implemented in each.

Two rules:

* A missing file means nothing has been recorded yet, and the caller's
  default stands in for it. A file that exists but cannot be read is
  corruption, and the run stops. Treating a truncated hashes.json as empty
  would make every source look new: each would be re-baselined, its real
  analysis overwritten with "Initial snapshot captured", and any change
  waiting to be analysed absorbed unreported into the new baseline.
* Every write goes to a temporary file first and is moved into place, so a
  run killed mid-write leaves the previous version rather than half a file.
"""

from __future__ import annotations

import json
import os
from typing import Any


class StateError(RuntimeError):
    """A state file exists but cannot be read."""


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StateError(f"{path} exists but could not be read ({exc}); fix or restore it from git") from exc


def save_json(data: Any, path: str, *, indent: int = 2) -> None:
    _replace(path, json.dumps(data, indent=indent, ensure_ascii=False) + "\n")


def read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_text(path: str, text: str) -> None:
    _replace(path, text)


def remove(path: str) -> None:
    if os.path.exists(path):
        os.remove(path)


def _replace(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text)
    os.replace(tmp, path)
