"""AI Steward Dashboard — AI transparency statements.

Every Commonwealth entity under the Policy for the responsible use of AI in
government publishes an AI transparency statement, and the DTA's central
register links to them. This keeps the dashboard's third stream: not a
change to a policy that binds the reader, and not an AI incident, but what
agencies say about their own use of AI.

    register -> links -> each statement through the policy monitor's gates
             -> one batched model call for the statements that changed

The register is compared as a list, so who joined, left or moved address
costs nothing. Each statement is fetched, validated, normalised, hashed and
diffed by the same `process_document` the policy monitor uses, so a
re-typeset page, a block page or a flip-flopping CDN is set aside here too.

    python transparency_watch.py                  # read, compare, summarise, write
    python transparency_watch.py --dry-run        # everything except writing
    python transparency_watch.py --only ip-australia --no-summary

Outputs:
    transparency/statements.json   the register's state and every statement's
    transparency/events.json       who joined, left or moved; what changed
    transparency/snapshots/        each statement's current text
    transparency/diffs/            each statement's most recent analysed diff
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import urlparse

from steward import configure_logging, diffing, fetching, health, monitor, store, transparency, web
from steward.config import ConfigError, load_config

TRANSPARENCY_DIR = "transparency"
STATEMENTS_FILE = os.path.join(TRANSPARENCY_DIR, "statements.json")
EVENTS_FILE = os.path.join(TRANSPARENCY_DIR, "events.json")
SNAPSHOT_DIR = os.path.join(TRANSPARENCY_DIR, "snapshots")
DIFF_DIR = os.path.join(TRANSPARENCY_DIR, "diffs")

AEST_TZ = timezone(timedelta(hours=10))

log = logging.getLogger("steward.transparency")


# --- Files -----------------------------------------------------------------------


def snapshot_path(statement_id: str) -> str:
    return os.path.join(SNAPSHOT_DIR, f"{statement_id}.txt")


def diff_path(statement_id: str) -> str:
    return os.path.join(DIFF_DIR, f"{statement_id}.diff")


def held_documents(held: dict) -> List[Tuple[str, dict]]:
    """(url, record) for the register and every statement, for the fetch session."""
    pairs = []
    register = held.get("register") or {}
    if register.get("url"):
        pairs.append((register["url"], register.get("document") or {}))
    for entry in held.get("statements") or []:
        if isinstance(entry, dict) and entry.get("url"):
            pairs.append((entry["url"], entry.get("document") or {}))
    return pairs


# --- The register ----------------------------------------------------------------


def read_register(
    cfg, held_register: dict, held_list: List[dict], session, timestamp: str
) -> Tuple[dict, List[dict], List[dict]]:
    """The register's record, the statements it lists, and what moved.

    When the register cannot be read, or reads implausibly, the list already
    held is kept and monitoring of each statement carries on.
    """
    tcfg = cfg.transparency
    url = tcfg.register_url
    prior_doc = held_register.get("document") if held_register.get("url") == url else {}
    prior_doc = prior_doc or {}

    result = fetching.fetch_document(
        {"url": url, "selector": tcfg.register_selector}, prior_doc, cfg, session=session
    )
    document = {
        **{key: prior_doc.get(key) for key in ("etag", "last_modified")},
        **monitor.fetch_route_fields(result, prior_doc, timestamp),
        "http_status": result.http_status,
        "fetch_ms": result.duration_ms,
    }
    record = {
        "url": url,
        "last_checked": timestamp,
        "last_success": held_register.get("last_success"),
        "page_updated": held_register.get("page_updated"),
        "consecutive_failures": int(held_register.get("consecutive_failures", 0) or 0),
        "last_error": "",
        "document": document,
    }

    listed, events, error = held_list, [], ""
    if result.status == fetching.NOT_MODIFIED:
        log.info("  Register not modified since the last read")
    elif result.ok and result.html:
        parsed = transparency.parse_register(result.html, url, tcfg.register_selector)
        plausible, why = transparency.register_is_plausible(
            parsed,
            {entry["id"] for entry in held_list},
            min_statements=tcfg.min_statements,
            keep_ratio=tcfg.keep_ratio,
            max_new=tcfg.max_new_statements,
        )
        if plausible:
            listed = [statement.as_dict() for statement in parsed]
            # The first read is a baseline, not 140 agencies joining at once.
            events = transparency.register_events(held_list, parsed) if held_list else []
            record["page_updated"] = transparency.register_updated(result.text) or record["page_updated"]
            document.update({"etag": result.etag, "last_modified": result.last_modified})
            log.info("  Register lists %d statement(s)", len(listed))
        else:
            error = f"register read rejected: {why}"
    else:
        error = result.error or "the register page came back empty"

    if error:
        log.warning("  %s — keeping the %d statement(s) already held", error, len(held_list))
        record["consecutive_failures"] += 1
        record["last_error"] = error
    else:
        record["consecutive_failures"] = 0
        record["last_success"] = timestamp

    record["status"] = health.document_status(record, cfg.health.consecutive_failure_threshold)
    record["counts"] = {
        obligation: sum(1 for entry in listed if entry.get("obligation") == obligation)
        for obligation in transparency.OBLIGATIONS
    }
    return record, listed, events


# --- The run ---------------------------------------------------------------------


def run(
    cfg,
    *,
    dry_run: bool = False,
    only: Optional[Sequence[str]] = None,
    summarise: bool = True,
) -> int:
    tcfg = cfg.transparency
    if not tcfg.enabled:
        log.info("Transparency statements are disabled in the config")
        return 0

    timestamp = datetime.now(AEST_TZ).isoformat()
    held = store.load_json(STATEMENTS_FILE, {})
    if not isinstance(held, dict):
        raise store.StateError(f"{STATEMENTS_FILE} must contain a JSON object")
    held_statements = {
        entry["id"]: entry
        for entry in held.get("statements") or []
        if isinstance(entry, dict) and entry.get("id") and entry.get("url")
    }
    log.info("Transparency statements: %d held%s", len(held_statements), " [dry-run]" if dry_run else "")

    # ~140 agency sites: a shorter plain-HTTP wait, and one attempt each — a
    # statement that cannot be read today is read tomorrow.
    statement_cfg = replace(
        cfg, fetch=replace(cfg.fetch, timeout_seconds=tcfg.fetch_timeout_seconds, max_retries=1)
    )
    session = fetching.FetchSession.remembering(held_documents(held), cfg.fetch.blocked_host_recheck_days)
    threshold = cfg.health.consecutive_failure_threshold

    statements: Dict[str, dict] = {}
    changes: List[dict] = []
    pending: Dict[str, tuple] = {}
    texts: Dict[str, str] = {}
    try:
        register, listed, events = read_register(
            cfg, held.get("register") or {}, list(held_statements.values()), session, timestamp
        )
        for event in events:
            event["timestamp"] = timestamp
            log.info("  Register: %s %s", event["type"], event["agency"])

        wanted = set(only or [])
        for listing in listed:
            sid = listing["id"]
            prior_entry = held_statements.get(sid, {})
            if wanted and sid not in wanted:
                if prior_entry:
                    statements[sid] = {**prior_entry, **listing}
                continue

            # A statement at a new address starts a new baseline.
            relinked = bool(prior_entry) and prior_entry.get("url") != listing["url"]
            prior_doc = {} if relinked or not prior_entry else prior_entry.get("document") or {}
            stored = "" if relinked else store.read_text(snapshot_path(sid))

            log.info("  %s", listing["agency"])
            record, outcome, diff, text = check_statement(listing, prior_doc, stored, statement_cfg, timestamp, session)
            entry = {
                **listing,
                "first_seen": prior_entry.get("first_seen") or timestamp,
                "statement_date": (text and transparency.statement_date(text)) or prior_entry.get("statement_date"),
                "last_change": None if relinked else prior_entry.get("last_change"),
                "document": record,
            }
            entry["status"] = health.document_status(record, threshold)
            statements[sid] = entry

            if outcome == monitor.DOC_CHANGED and diff is not None:
                changes.append({"id": sid, "agency": listing["agency"], "diff": diff.text[: tcfg.max_diff_chars]})
                pending[sid] = (text, diff, prior_doc)
            elif outcome in monitor.BASELINE_OUTCOMES:
                texts[sid] = text
    finally:
        session.close()

    diffs: Dict[str, str] = {}
    results: Dict[str, dict] = {}
    if changes and not dry_run and summarise and tcfg.summarise:
        summary = transparency.summarise(changes, model=cfg.model, batch_size=tcfg.summary_batch_size)
        results = summary.results
        log.info(
            "  Summarised %d of %d changed statement(s) in %d call(s), %d prompt / %d output tokens",
            len(results),
            len(changes),
            summary.calls,
            summary.prompt_tokens,
            summary.output_tokens,
        )
    elif changes:
        log.info("  %d statement(s) changed; not summarised this run", len(changes))

    for change in changes:
        sid = change["id"]
        text, diff, prior_doc = pending[sid]
        entry = statements[sid]
        result = results.get(sid)
        if result is None:
            # Nothing is stored, so the same change is summarised next run
            # rather than lost.
            entry["document"] = {
                **entry["document"],
                **{key: prior_doc.get(key) for key in ("hash", "length", "previous_hashes")},
                "status": "analysis_pending",
            }
            continue
        texts[sid] = text
        diffs[sid] = diff.text
        entry["last_change"] = {
            "timestamp": timestamp,
            "verdict": result["verdict"],
            "summary": result["summary"],
            "added": diff.added,
            "removed": diff.removed,
        }
        events.append(
            {
                "type": transparency.UPDATED if result["verdict"] == transparency.MATERIAL_CHANGE else transparency.REWORDED,
                "timestamp": timestamp,
                **{key: entry[key] for key in ("id", "agency", "portfolio", "obligation", "url")},
                "summary": result["summary"],
                "added": diff.added,
                "removed": diff.removed,
            }
        )

    removed = [sid for sid in held_statements if sid not in {entry["id"] for entry in listed}]

    if dry_run:
        _report_dry_run(register, statements, events, changes, removed)
        return 0

    for sid, text in texts.items():
        store.write_text(snapshot_path(sid), text)
    for sid, text in diffs.items():
        store.write_text(diff_path(sid), text)
    for sid in removed:
        store.remove(snapshot_path(sid))
        store.remove(diff_path(sid))

    store.save_json(
        {
            "generated_at": timestamp,
            "register": register,
            "statements": sorted(
                statements.values(),
                key=lambda e: (transparency.OBLIGATIONS.index(e.get("obligation", transparency.MANDATORY)), e.get("portfolio") or "", e["agency"]),
            ),
        },
        STATEMENTS_FILE,
    )
    store.save_json(prune_events(events + store.load_json(EVENTS_FILE, []), tcfg.event_days), EVENTS_FILE)

    failing = sum(1 for entry in statements.values() if entry.get("status") == health.FAILING)
    log.info(
        "Transparency run complete — %d statement(s), %d event(s), %d failing, register %s",
        len(statements),
        len(events),
        failing,
        register["status"],
    )
    # Worth a red run only when nothing at all could be read.
    readable = register["status"] != health.FAILING or any(
        entry.get("document", {}).get("last_success") == timestamp for entry in statements.values()
    )
    return 0 if readable else 1


def check_statement(
    listing: dict, prior_doc: dict, stored: str, cfg, timestamp: str, session
) -> Tuple[dict, str, Optional[diffing.DiffResult], str]:
    """One statement through the gates, never raising.

    A host that is not on the allowlist is not visited at all. Anything that
    goes wrong reading one agency's page — a PDF the parser chokes on, a
    browser crash — fails that statement alone and the run carries on, as a
    fetch failure does.
    """
    url_data = {"url": listing["url"], "label": listing["agency"]}
    tcfg = cfg.transparency
    if not transparency.host_allowed(listing["url"], tcfg.allowed_host_suffixes, set(tcfg.allowed_hosts)):
        host = urlparse(listing["url"]).hostname or listing["url"]
        error = f"not fetched: {host} is not in transparency.allowed_hosts in steward_config.yaml"
        log.warning("    %s", error)
        return monitor.failed_document(url_data, prior_doc, timestamp, error), monitor.DOC_FETCH_FAILED, None, stored
    try:
        return monitor.check_document(url_data, prior_doc, cfg, timestamp, stored_text=stored, session=session)
    except Exception as exc:  # noqa: BLE001 — one agency's page must not cost the other statements
        log.exception("    Unhandled error checking %s", listing["url"])
        return (
            monitor.failed_document(url_data, prior_doc, timestamp, web.describe_error(exc)),
            monitor.DOC_FETCH_FAILED,
            None,
            stored,
        )


def prune_events(events: List[dict], days: int, now: Optional[datetime] = None) -> List[dict]:
    """Newest first, and none older than `days`."""
    now = now or datetime.now(AEST_TZ)
    cutoff = now - timedelta(days=days)
    kept = []
    for event in events:
        if not isinstance(event, dict):
            continue
        try:
            when = datetime.fromisoformat(event.get("timestamp", ""))
        except ValueError:
            continue
        if when.tzinfo is None:
            when = when.replace(tzinfo=AEST_TZ)
        if when >= cutoff:
            kept.append(event)
    return sorted(kept, key=lambda e: e["timestamp"], reverse=True)


def _report_dry_run(register: dict, statements: dict, events: List[dict], changes: List[dict], removed: List[str]) -> None:
    log.info("--- dry run summary ---")
    log.info("  register: %s %s", register["status"], register.get("last_error") or "")
    log.info("  statements listed: %d (%s)", len(statements), register["counts"])
    for event in events:
        log.info("  would record: %s %s", event["type"], event["agency"])
    for sid in removed:
        log.info("  would stop monitoring: %s", sid)
    log.info("  changed statements that would be summarised: %d", len(changes))
    log.info("Nothing was written to disk.")


# --- Entry point -----------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the AI transparency statements.")
    parser.add_argument("--dry-run", action="store_true", help="Read and compare, but write nothing.")
    parser.add_argument("--config", default="steward_config.yaml", help="Path to the config file.")
    parser.add_argument(
        "--only", action="append", default=None, metavar="STATEMENT_ID",
        help="Check only this statement (its id in transparency/statements.json). Repeatable. "
        "The register is always read.",
    )
    parser.add_argument(
        "--no-summary", action="store_true",
        help="Skip the model; changed statements wait for the next run.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    configure_logging()
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("Configuration error — %s", exc)
        return 1
    if not args.no_summary and not args.dry_run and not os.environ.get("GEMINI_API_KEY"):
        log.warning("GEMINI_API_KEY is not set — changed statements will wait for the next run")
    try:
        return run(cfg, dry_run=args.dry_run, only=args.only, summarise=not args.no_summary)
    except store.StateError as exc:
        log.error("Stopping without writing anything: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
