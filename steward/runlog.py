"""One JSON record per document per run, appended to runs.jsonl.

Without this you cannot answer "how often does Perplexity actually change?"
or "what is this costing?" — and both questions get sharper the moment
anything else starts making model calls. It is also what lets the size-delta
thresholds be calibrated against real distributions rather than guesses.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List

log = logging.getLogger(__name__)

RUN_LOG_FILE = "runs.jsonl"


class RunLog:
    def __init__(self, run_id: str, path: str = RUN_LOG_FILE) -> None:
        self.run_id = run_id
        self.path = path
        self.records: List[Dict[str, Any]] = []

    def record(self, **fields: Any) -> Dict[str, Any]:
        entry = {"run_id": self.run_id, **fields}
        self.records.append(entry)
        return entry

    def flush(self, retention_days: int = 90) -> None:
        """Append this run's records, dropping anything past retention."""
        kept = _load_recent(self.path, retention_days)
        kept.extend(self.records)
        tmp = f"{self.path}.tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            for entry in kept:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        os.replace(tmp, self.path)
        log.info("Run log: %d records this run, %d retained", len(self.records), len(kept))

    # --- Summaries used by the health check and the run's closing log ---

    def counts_by_outcome(self) -> Dict[str, int]:
        counts: Dict[str, int] = {}
        for entry in self.records:
            outcome = entry.get("outcome", "unknown")
            counts[outcome] = counts.get(outcome, 0) + 1
        return counts

    def token_totals(self) -> Dict[str, int]:
        return {
            "prompt_tokens": sum(e.get("prompt_tokens", 0) for e in self.records),
            "output_tokens": sum(e.get("output_tokens", 0) for e in self.records),
            "llm_calls": sum(1 for e in self.records if e.get("llm_called")),
        }


def _load_recent(path: str, retention_days: int) -> List[Dict[str, Any]]:
    if not os.path.exists(path):
        return []

    cutoff = datetime.now().astimezone() - timedelta(days=retention_days)
    kept: List[Dict[str, Any]] = []
    with open(path, "r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = entry.get("timestamp")
            if timestamp:
                try:
                    if datetime.fromisoformat(timestamp) < cutoff:
                        continue
                except ValueError:
                    pass
            kept.append(entry)
    return kept


def load_records(path: str = RUN_LOG_FILE, days: int = 90) -> List[Dict[str, Any]]:
    """Read back recent records, for reporting."""
    return _load_recent(path, days)


def error_rate(records: Iterable[Dict[str, Any]]) -> float:
    records = list(records)
    if not records:
        return 0.0
    failures = sum(
        1 for e in records if e.get("outcome") in ("fetch_failed", "suspect_scrape", "schema_failed")
    )
    return failures / len(records)
