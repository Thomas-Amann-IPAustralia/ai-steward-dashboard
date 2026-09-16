"""Source health: make a broken source visible.

A steward cannot currently distinguish "stable since February" from "has not
been successfully read since February", and the second is a silent false
negative on exactly the risk this tool exists to cover. When every fetch for
a set failed, the previous entry was copied forward and the UI showed nothing
unusual.

Health is derived from the per-document records in hashes.json, written to
health.json for the dashboard, and — when a source crosses a threshold —
emitted as an alert the workflow turns into a GitHub issue.

Alerts fire on transitions, not on states. Alerting on a state meant one
comment per run for as long as a source stayed broken: digital.gov.au produced
thirty-five identical tables on one issue, which is how it came to be ignored
for a month. An alert now says what *changed* — a source that started failing,
or one that recovered — and anything still open is repeated at most once a week
as a digest. health_state.json records what has already been reported.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

HEALTH_FILE = "health.json"
ALERT_FILE = "health_alert.md"
STATE_FILE = "health_state.json"

OK = "ok"
DEGRADED = "degraded"
FAILING = "failing"
DISABLED = "disabled"

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

        # A source nobody is checking cannot be failing. It is reported so the
        # dashboard can say "not monitored, and here is why" rather than
        # presenting a months-old reading as current, but it raises no alert
        # and does not drag the overall status down.
        if entry.get("monitoring") == DISABLED:
            sources[set_name] = {
                "file_id": entry.get("file_id"),
                "status": DISABLED,
                "disabled_reason": entry.get("disabled_reason", ""),
                "disabled_since": entry.get("disabled_since"),
                "last_success": entry.get("last_success"),
                "days_since_success": _days_since(entry.get("last_success")),
                "consecutive_failures": 0,
                "documents_total": len(documents),
                "documents_failing": 0,
                "failing": [],
            }
            continue

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

    monitored = sum(1 for s in sources.values() if s["status"] != DISABLED)

    return {
        "generated_at": datetime.now().astimezone().isoformat(),
        "overall": overall,
        "error_rate": round(run_error_rate, 4),
        "monitored_sources": monitored,
        "sources": sources,
        "alerts": alerts,
    }


def write_report(report: Dict[str, Any], path: str = HEALTH_FILE) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)


def alert_key(alert: Dict[str, Any]) -> str:
    """Stable identity for an alert across runs.

    Deliberately coarse: it excludes `detail` and the failure count, so a source
    that fails again tomorrow with one more failure on the counter is the same
    alert, not a new one.
    """
    return "|".join(
        (alert.get("kind", ""), alert.get("set_name", ""), alert.get("url", ""))
    )


def load_state(path: str = STATE_FILE) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {"open": {}, "last_digest_at": None}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            state = json.load(handle)
    except (OSError, json.JSONDecodeError):
        log.warning("health state at %s is unreadable; treating every alert as new", path)
        return {"open": {}, "last_digest_at": None}
    if not isinstance(state, dict):
        return {"open": {}, "last_digest_at": None}
    state.setdefault("open", {})
    state.setdefault("last_digest_at", None)
    return state


def save_state(state: Dict[str, Any], path: str = STATE_FILE) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(state, handle, indent=2, ensure_ascii=False)


def _digest_due(state: Dict[str, Any], now: datetime, digest_days: int) -> bool:
    last = state.get("last_digest_at")
    if not last:
        return True
    try:
        then = datetime.fromisoformat(last)
    except (TypeError, ValueError):
        return True
    if then.tzinfo is None:
        then = then.astimezone()
    return (now - then).days >= digest_days


@dataclass
class AlertDelta:
    new: List[Dict[str, Any]] = field(default_factory=list)
    recovered: List[Dict[str, Any]] = field(default_factory=list)
    ongoing: List[Dict[str, Any]] = field(default_factory=list)
    digest_due: bool = False

    @property
    def worth_reporting(self) -> bool:
        return bool(self.new or self.recovered or (self.ongoing and self.digest_due))


def diff_alerts(
    state: Dict[str, Any],
    report: Dict[str, Any],
    now: Optional[datetime] = None,
    digest_days: int = 7,
) -> AlertDelta:
    """What changed since the last report, rather than what is currently wrong."""
    now = now or datetime.now().astimezone()
    previously_open = state.get("open", {}) or {}
    current = {alert_key(alert): alert for alert in report.get("alerts", [])}

    delta = AlertDelta(digest_due=_digest_due(state, now, digest_days))
    for key, alert in current.items():
        seen = previously_open.get(key)
        enriched = {**alert, "first_seen": (seen or {}).get("first_seen") or now.isoformat()}
        if seen is None:
            delta.new.append(enriched)
        else:
            delta.ongoing.append(enriched)

    for key, alert in previously_open.items():
        if key not in current:
            delta.recovered.append(alert)

    return delta


def _cell(value: Any) -> str:
    """A table cell. Every one is escaped: a pipe anywhere in a source name, a
    URL or an error message silently splits the row otherwise."""
    return str(value).replace("|", "\\|") if value not in (None, "", 0) else "—"


def _alert_row(alert: Dict[str, Any]) -> str:
    return "| {set_name} | {url} | {kind} — {detail} | {failures} | {last_success} |".format(
        set_name=_cell(alert.get("set_name")),
        url=_cell(alert.get("url")),
        kind=_cell(alert.get("kind")),
        detail=_cell(alert.get("detail")),
        failures=alert.get("consecutive_failures") or 0,
        last_success=_cell(alert.get("last_success")) if alert.get("last_success") else "never",
    )


_TABLE_HEAD = [
    "| Source | Document | Problem | Consecutive failures | Last success |",
    "| --- | --- | --- | --- | --- |",
]


def render_alert_markdown(delta: AlertDelta, report: Dict[str, Any]) -> str:
    """Issue body describing the transitions. Empty when nothing transitioned."""
    if not delta.worth_reporting:
        return ""

    lines: List[str] = []

    if delta.new:
        lines += [
            f"## {len(delta.new)} source(s) started failing",
            "",
            *_TABLE_HEAD,
            *[_alert_row(alert) for alert in delta.new],
            "",
            "A source in this state is not reporting 'no changes' — it is reporting "
            "nothing at all. Check the source URL first (a 404 means it moved, and "
            "the fix is in `policy_sets.json`), then the extraction path in "
            "`steward/fetching.py`.",
            "",
        ]

    if delta.recovered:
        lines += [
            f"## {len(delta.recovered)} source(s) recovered",
            "",
            *[
                f"- **{alert.get('set_name') or '—'}** "
                f"{alert.get('url') or ''} — {alert.get('kind')}".rstrip()
                for alert in delta.recovered
            ],
            "",
        ]

    if delta.ongoing and delta.digest_due:
        lines += [
            f"## Still open ({len(delta.ongoing)})",
            "",
            "Repeated weekly. Nothing here has changed since it was first reported.",
            "",
            *_TABLE_HEAD,
            *[_alert_row(alert) for alert in delta.ongoing],
            "",
        ]

    lines += [
        "---",
        f"Run generated {report.get('generated_at')} · overall status "
        f"**{report.get('overall')}** · {report.get('monitored_sources', '?')} "
        "source(s) monitored.",
    ]
    return "\n".join(lines)


def write_alert(
    report: Dict[str, Any],
    path: str = ALERT_FILE,
    state_path: str = STATE_FILE,
    digest_days: int = 7,
    now: Optional[datetime] = None,
) -> bool:
    """Write the transition report, if there is one, and record what was said.

    The state file is updated whether or not anything is written, so that a
    recovery is still detected on the run after a silent one.
    """
    now = now or datetime.now().astimezone()
    state = load_state(state_path)
    delta = diff_alerts(state, report, now=now, digest_days=digest_days)
    body = render_alert_markdown(delta, report)

    state["open"] = {
        alert_key(alert): {
            "kind": alert.get("kind"),
            "set_name": alert.get("set_name"),
            "url": alert.get("url"),
            "detail": alert.get("detail"),
            "first_seen": alert.get("first_seen"),
            "last_seen": now.isoformat(),
        }
        for alert in delta.new + delta.ongoing
    }
    state["updated_at"] = now.isoformat()
    if delta.ongoing and delta.digest_due:
        state["last_digest_at"] = now.isoformat()
    save_state(state, state_path)

    if not body:
        return False
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(body)
    return True
