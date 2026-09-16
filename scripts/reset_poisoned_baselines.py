"""Delete stored baselines that are block pages rather than policy documents.

`validate_capture` only updates a document's stored `length` when a capture
passes, so a baseline recorded before validation existed is never corrected by
running the pipeline again — it just sits there, and every subsequent capture
is measured against it. hashes.json currently holds a 347-character Imperva
interstitial and an 84-character Chrome error page as the reference text for
five documents.

There is no in-place fix for that: the stored text is not a shrunken version of
the document, it is a different document. The record has to go so the next run
treats the URL as a first capture.

A baseline is suspect when the stored `length` is below the configured
`validation.min_length` — a passing capture cannot be, so anything that is
predates the gate.

    python scripts/reset_poisoned_baselines.py --dry-run
    python scripts/reset_poisoned_baselines.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from steward import health  # noqa: E402
from steward.config import load_config  # noqa: E402

HASHES_FILE = "hashes.json"
SNAPSHOTS_DIR = "snapshots"


def reset(dry_run: bool = False) -> int:
    cfg = load_config("steward_config.yaml")
    floor = cfg.validation.min_length

    with open(HASHES_FILE, "r", encoding="utf-8") as handle:
        hashes = json.load(handle)

    with open("policy_sets.json", "r", encoding="utf-8") as handle:
        configured = {
            ps["setName"]: {u["url"] for u in ps.get("urls", [])}
            for ps in json.load(handle)
        }

    removed = 0
    for set_name, entry in hashes.items():
        documents = entry.get("documents") or {}
        file_id = entry.get("file_id")
        still_configured = configured.get(set_name, set())
        drop = []

        for url, record in documents.items():
            length = record.get("length")
            if url not in still_configured and set_name in configured:
                drop.append((url, record, "no longer in policy_sets.json"))
            elif isinstance(length, int) and 0 < length < floor:
                drop.append(
                    (url, record, f"stored baseline is {length} chars, below the {floor} floor")
                )

        for url, record, why in drop:
            print(f"  ✂  {set_name} / {record.get('label', url)}: {why}")
            removed += 1
            if dry_run:
                continue

            documents.pop(url, None)
            snapshot = os.path.join(SNAPSHOTS_DIR, file_id or "", f"{record.get('doc_id')}.txt")
            if record.get("doc_id") and os.path.exists(snapshot):
                os.remove(snapshot)

        if drop and not dry_run:
            # The set-level failure counter was counting these documents. It is
            # not a record of anything once they are gone.
            entry["consecutive_failures"] = 0
            entry["status"] = health.set_status(
                documents, cfg.health.consecutive_failure_threshold
            )

    if not dry_run and removed:
        with open(HASHES_FILE, "w", encoding="utf-8") as handle:
            json.dump(hashes, handle, indent=4, ensure_ascii=False)

    return removed


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Report, change nothing.")
    args = parser.parse_args(argv)

    count = reset(args.dry_run)
    if count == 0:
        print("No poisoned baselines found.")
    else:
        verb = "would be reset" if args.dry_run else "reset"
        print(f"{count} document baseline(s) {verb}. The next run recaptures them.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
