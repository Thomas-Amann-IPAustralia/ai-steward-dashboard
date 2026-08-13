"""Build history.json, the index over the archived analyses in logs/.

The archive has been accumulating for a year and is already copied into every
build, but GitHub Pages serves no directory listing, so the app has never been
able to enumerate it. One index generated at the end of each run turns the
timeline into a rendering job over data already collected.

Filenames are `{file_id}_{YYYYmmdd}_{HHMMSS}_analysis.json`, matching the 500+
archives already on disk.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta
from typing import Any, Dict, List

log = logging.getLogger(__name__)

HISTORY_FILE = "history.json"
_ARCHIVE_RE = re.compile(r"^(?P<file_id>.+)_(?P<stamp>\d{8}_\d{6})_analysis\.json$")


def _parse_stamp(stamp: str) -> str | None:
    try:
        return datetime.strptime(stamp, "%Y%m%d_%H%M%S").isoformat()
    except ValueError:
        return None


def build_index(log_dir: str, known_file_ids: set[str] | None = None) -> Dict[str, Any]:
    """Index every archived analysis, newest first, grouped by file_id."""
    entries: Dict[str, List[Dict[str, Any]]] = {}

    if not os.path.isdir(log_dir):
        return {"generated_at": datetime.now().astimezone().isoformat(), "entries": {}}

    for name in sorted(os.listdir(log_dir)):
        match = _ARCHIVE_RE.match(name)
        if not match:
            continue

        file_id = match.group("file_id")
        if known_file_ids is not None and file_id not in known_file_ids:
            # Orphans from sources no longer monitored stay on disk but out of
            # the index, so the UI never links to a policy it cannot show.
            continue

        timestamp = _parse_stamp(match.group("stamp"))
        if timestamp is None:
            continue

        record: Dict[str, Any] = {
            "timestamp": timestamp,
            "analysis_path": f"logs/{name}",
        }

        snapshot = name.replace("_analysis.json", "_snapshot.txt")
        if os.path.exists(os.path.join(log_dir, snapshot)):
            record["snapshot_path"] = f"logs/{snapshot}"

        diff = name.replace("_analysis.json", "_diff.txt")
        if os.path.exists(os.path.join(log_dir, diff)):
            record["diff_path"] = f"logs/{diff}"

        try:
            with open(os.path.join(log_dir, name), "r", encoding="utf-8") as handle:
                analysis = json.load(handle)
        except (OSError, json.JSONDecodeError):
            analysis = {}

        if isinstance(analysis, dict):
            record["priority"] = analysis.get("priority")
            record["verdict"] = analysis.get("verdict")
            record["summary"] = analysis.get("summary")
            record["changed_documents"] = analysis.get("changed_documents", [])

        entries.setdefault(file_id, []).append(record)

    for records in entries.values():
        records.sort(key=lambda r: r["timestamp"], reverse=True)

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "entries": entries,
    }


def write_index(index: Dict[str, Any], path: str = HISTORY_FILE) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(index, handle, indent=2, ensure_ascii=False)
    total = sum(len(v) for v in index.get("entries", {}).values())
    log.info("History index: %d archived analyses across %d sources", total, len(index.get("entries", {})))


def prune(log_dir: str, retention_days: int) -> int:
    """Delete archives past retention. Returns the number removed."""
    if not os.path.isdir(log_dir):
        return 0

    cutoff = datetime.now() - timedelta(days=retention_days)
    removed = 0
    for name in os.listdir(log_dir):
        match = re.match(r"^.+_(\d{8}_\d{6})_(?:analysis\.json|snapshot\.txt|diff\.txt)$", name)
        if not match:
            continue
        try:
            when = datetime.strptime(match.group(1), "%Y%m%d_%H%M%S")
        except ValueError:
            continue
        if when < cutoff:
            try:
                os.remove(os.path.join(log_dir, name))
                removed += 1
            except OSError as exc:
                log.warning("Could not prune %s: %s", name, exc)
    return removed
