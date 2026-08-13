"""Source health: make a broken source visible.

A steward cannot currently distinguish "stable since February" from "has not
been successfully read since February", and the second is a silent false
negative on exactly the risk this tool exists to cover. When every fetch for
a set failed, the previous entry was copied forward and the UI showed nothing
unusual.

Health is derived from the per-document records in hashes.json, written to
health.json for the dashboard, and — when a source crosses a threshold —
emitted as an alert the workflow turns into a GitHub issue.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List

log = logging.getLogger(__name__)

HEALTH_FILE = "health.json"
ALERT_FILE = "health_alert.md"

OK = "ok"
DEGRADED = "degraded"
FAILING = "failing"

_RANK = {OK: 0, DEGRADED: 1, FAILING: 2}


def document_status(record: Dict[str, Any], threshold: int) -> str:
    failures = int(record.get("consecutive_failures", 0) or 0)
    if failures >= threshold:
        return FAILING
    if failures > 0:
        return DEGRADED
    return OK


def set_status(documents: Dict[str, Any], threshold: int) -> str:
    if not documents:
        return FAILING
    worst = OK
    for record in documents.values():
        status = document_status(record, threshold)
        if _RANK[status] > _RANK[worst]:
            worst = status
    return worst


def _days_since(timestamp: str | None) -> int | None:
    if not timestamp:
        return None
    try:
        then = datetime.fromisoformat(timestamp)
    except ValueError:
        return None
    now = datetime.now(then.tzinfo) if then.tzinfo else datetime.now()
    return max(0, (now - then).days)


def build_report(hashes: Dict[str, Any], cfg, run_error_rate: float = 0.0) -> Dict[str, Any]:
    """Health summary for every monitored set, plus the alerts worth raising."""
    threshold = cfg.health.consecutive_failure_threshold
    sources: Dict[str, Any] = {}
    alerts: List[Dict[str, Any]] = []

    for set_name, entry in hashes.items():
        documents = entry.get("documents", {}) or {}
        status = entry.get("status") or set_status(documents, threshold)

        failing_docs = [
            {
                "url": url,
                "label": record.get("label", url),
                "consecutive_failures": record.get("consecutive_failures", 0),
                "last_success": record.get("last_success"),
                "last_error": record.get("last_error", ""),
                "status": document_status(record, threshold),
            }
            for url, record in documents.items()
            if document_status(record, threshold) != OK
        ]

        sources[set_name] = {
            "file_id": entry.get("file_id"),
            "status": status,
            "last_success": entry.get("last_success"),
            "days_since_success": _days_since(entry.get("last_success")),
            "consecutive_failures": entry.get("consecutive_failures", 0),
            "documents_total": len(documents),
            "documents_failing": len(failing_docs),
            "failing": failing_docs,
        }

        for doc in failing_docs:
            if doc["status"] == FAILING:
                alerts.append(
                    {
                        "kind": "source_failing",
                        "set_name": set_name,
                        "url": doc["url"],
                        "consecutive_failures": doc["consecutive_failures"],
                        "last_success": doc["last_success"],
                        "detail": doc["last_error"],
                    }
                )

        if int(entry.get("schema_failures", 0) or 0) >= cfg.health.schema_failure_threshold:
            alerts.append(
                {
                    "kind": "schema_failures",
                    "set_name": set_name,
                    "url": "",
                    "consecutive_failures": entry.get("schema_failures"),
                    "last_success": entry.get("last_success"),
                    "detail": "the model returned an invalid response on consecutive runs",
                }
            )

    if run_error_rate > cfg.health.error_rate_threshold:
        alerts.append(
            {
                "kind": "run_error_rate",
                "set_name": "",
                "url": "",
                "consecutive_failures": 0,
                "last_success": None,
                "detail": (
                    f"{run_error_rate:.0%} of documents failed this run, above the "
                    f"{cfg.health.error_rate_threshold:.0%} threshold"
                ),
            }
        )

    overall = OK
    for source in sources.values():
        if _RANK.get(source["status"], 0) > _RANK[overall]:
            overall = source["status"]

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "overall": overall,
        "error_rate": round(run_error_rate, 4),
        "sources": sources,
        "alerts": alerts,
    }


def write_report(report: Dict[str, Any], path: str = HEALTH_FILE) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def render_alert_markdown(report: Dict[str, Any]) -> str:
    """Issue body for the alerting step. Empty string when nothing is wrong."""
    alerts = report.get("alerts", [])
    if not alerts:
        return ""

    lines = [
        "The steward run finished with sources that need attention.",
        "",
        f"Generated: {report.get('generated_at')}",
        f"Overall status: **{report.get('overall')}**",
        "",
        "| Source | Document | Problem | Consecutive failures | Last success |",
        "| --- | --- | --- | --- | --- |",
    ]
    for alert in alerts:
        lines.append(
            "| {set_name} | {url} | {kind} — {detail} | {failures} | {last_success} |".format(
                set_name=alert.get("set_name") or "—",
                url=alert.get("url") or "—",
                kind=alert.get("kind"),
                detail=(alert.get("detail") or "").replace("|", "\\|") or "—",
                failures=alert.get("consecutive_failures") or 0,
                last_success=alert.get("last_success") or "never",
            )
        )

    lines += [
        "",
        "A source in this state is not reporting 'no changes' — it is reporting "
        "nothing at all. Check the source URL, then the extraction path in "
        "`steward/fetching.py`.",
    ]
    return "\n".join(lines)


def write_alert(report: Dict[str, Any], path: str = ALERT_FILE) -> bool:
    body = render_alert_markdown(report)
    if not body:
        return False
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return True
