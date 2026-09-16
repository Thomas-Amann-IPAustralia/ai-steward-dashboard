"""Retract an analysis the pipeline should never have published.

Distinct from `repair_legacy_analyses.py`, which mechanically corrects dates.
This is a judgement: a recorded "change" turned out to be an artefact of a bad
capture, and the dashboard is asserting something untrue about a real
organisation's policy until someone says otherwise.

The retraction is written in the shape `steward/analysis.py` produces, so the
frontend and `steward/history.py` read it like any other analysis, and the
badge is cleared from hashes.json. The original stays in `logs/` — the point is
to stop presenting it as current, not to erase that it happened.

    python scripts/retract_analysis.py "Perplexity AI Legal Policies" \
        --reason "..." --amended 2026-08-03T13:35:18+10:00 --dry-run
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

ANALYSIS_DIR = "analysis"
LOG_DIR = "logs"
HASHES_FILE = "hashes.json"
AEST_TZ = timezone(timedelta(hours=10))


def _stamp(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        return datetime.now(AEST_TZ).strftime("%Y%m%d_%H%M%S")


def retract(set_name: str, reason: str, amended: str | None, dry_run: bool) -> int:
    with open(HASHES_FILE, "r", encoding="utf-8") as handle:
        hashes = json.load(handle)

    entry = hashes.get(set_name)
    if entry is None:
        print(f"No policy set named {set_name!r} in {HASHES_FILE}.", file=sys.stderr)
        return 1

    file_id = entry.get("file_id")
    path = os.path.join(ANALYSIS_DIR, f"{file_id}.json")
    if not os.path.exists(path):
        print(f"No current analysis at {path}.", file=sys.stderr)
        return 1

    with open(path, "r", encoding="utf-8") as handle:
        current = json.load(handle)

    retracted_at = datetime.now(AEST_TZ).isoformat()
    stub = {
        "verdict": "no_material_change",
        "summary": f"Retracted: {reason}",
        "analysis": (
            f"**This analysis has been retracted.**\n\n{reason}\n\n"
            f"The retracted analysis was dated {current.get('date_time', 'an unknown date')} "
            f"and was rated `{current.get('priority', 'unknown')}`. It remains in `logs/` "
            "for the record, and appears in the change history below.\n\n"
            "Analyses recorded before 13 August 2026 predate the validation gates that "
            "now reject an implausible capture, and have not been individually audited."
        ),
        "priority": "low",
        "date_time": retracted_at,
        "changed_documents": [],
        "retracted": True,
    }

    print(f"  {set_name}")
    print(f"    analysis  {current.get('priority')} @ {current.get('date_time')} -> retracted")
    print(f"    badge     {entry.get('last_priority')} -> low")
    print(f"    amended   {entry.get('last_amended')} -> {amended or 'unchanged'}")

    if dry_run:
        return 0

    # Archive before overwriting, using the same naming grammar history.py parses.
    archived = os.path.join(
        LOG_DIR, f"{file_id}_{_stamp(current.get('date_time'))}_analysis.json"
    )
    if not os.path.exists(archived):
        shutil.copy(path, archived)

    with open(path, "w", encoding="utf-8") as handle:
        json.dump(stub, handle, indent=4, ensure_ascii=False)

    entry["last_priority"] = "low"
    entry["last_verdict"] = "no_material_change"
    entry["last_review"] = {
        "timestamp": retracted_at,
        "verdict": "no_material_change",
        "summary": f"Retracted: {reason}",
        "changed_documents": [],
    }
    if amended:
        entry["last_amended"] = amended
    entry.pop("last_change", None)

    with open(HASHES_FILE, "w", encoding="utf-8") as handle:
        json.dump(hashes, handle, indent=4, ensure_ascii=False)

    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("set_name")
    parser.add_argument("--reason", required=True, help="Why it is being retracted.")
    parser.add_argument(
        "--amended",
        default=None,
        help="ISO timestamp to roll last_amended back to. Omit to leave it alone.",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    return retract(args.set_name, args.reason, args.amended, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
