"""Flag pre-upgrade analyses and correct the dates the model invented.

Before `steward/analysis.py` stamped the timestamp in code, the model was asked
for one and supplied whatever it felt like. Four of the eight files in
`analysis/` still carry those inventions — the Perplexity set reads
"16 May 2024" on a change the pipeline recorded on 9 August 2026 — and because
those sources have not materially changed since, no run will ever overwrite
them.

A pre-upgrade analysis is identified by the absence of a `verdict` key: the
current pipeline always writes one, the old one never did. Two things happen
to it:

* `date_time` is replaced with `last_amended` from hashes.json, which the
  pipeline recorded itself and the model never touched.
* `legacy: true` is set, so the dashboard can say the analysis predates the
  current gates rather than presenting it as though it did not.

The archived copy in `logs/` keeps the original wording and the original
invented date; nothing here edits history.

Idempotent — a repaired file has a `verdict`-less body but a `legacy` flag, and
is skipped on a second run.

    python scripts/repair_legacy_analyses.py --dry-run
    python scripts/repair_legacy_analyses.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, Optional

ANALYSIS_DIR = "analysis"
HASHES_FILE = "hashes.json"


def load_json(path: str):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


# The pipeline writes `date_time` at the moment it writes `last_amended`, so
# the two differ by microseconds on a healthy record. Anything inside this
# window is the same event and is left alone; rewriting it would be churn.
SAME_EVENT_SECONDS = 300


def is_legacy(analysis: dict) -> bool:
    """Written before the schema contract existed."""
    return "verdict" not in analysis


def _parse(value: Optional[str]) -> Optional[datetime]:
    try:
        return datetime.fromisoformat((value or "").replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None


def dates_disagree(stated: Optional[str], recorded: Optional[str]) -> bool:
    """Whether the analysis and the pipeline are describing different moments."""
    if not recorded:
        return False
    if stated == recorded:
        return False

    left, right = _parse(stated), _parse(recorded)
    if left is None:
        return True
    if right is None:
        return False
    if left.tzinfo is None or right.tzinfo is None:
        return True
    return abs((left - right).total_seconds()) > SAME_EVENT_SECONDS


def file_id_index(hashes: Dict[str, dict]) -> Dict[str, dict]:
    """file_id -> the hashes.json entry that owns it."""
    return {
        entry["file_id"]: {"set_name": set_name, **entry}
        for set_name, entry in hashes.items()
        if entry.get("file_id")
    }


def repair(dry_run: bool = False) -> int:
    hashes = load_json(HASHES_FILE)
    by_file_id = file_id_index(hashes)
    repaired = 0

    for name in sorted(os.listdir(ANALYSIS_DIR)):
        if not name.endswith(".json"):
            continue

        path = os.path.join(ANALYSIS_DIR, name)
        analysis = load_json(path)
        if not is_legacy(analysis):
            continue

        file_id = name[: -len(".json")]
        entry = by_file_id.get(file_id)
        if entry is None:
            print(f"  ?  {file_id}: no hashes.json entry, left alone")
            continue

        recorded = entry.get("last_amended")
        stated = analysis.get("date_time")
        changes = []

        if dates_disagree(stated, recorded):
            analysis["date_time"] = recorded
            changes.append(f"date {stated} -> {recorded}")
        if not analysis.get("legacy"):
            analysis["legacy"] = True
            changes.append("flagged legacy")

        if not changes:
            continue

        print(f"  ✎  {entry['set_name']}: {'; '.join(changes)}")
        repaired += 1
        if not dry_run:
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(analysis, handle, indent=4, ensure_ascii=False)

    return repaired


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report, change nothing.")
    args = parser.parse_args(argv)

    count = repair(args.dry_run)
    if count == 0:
        print("Nothing to repair.")
    else:
        print(f"{count} analysis file(s) {'would be ' if args.dry_run else ''}repaired.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
