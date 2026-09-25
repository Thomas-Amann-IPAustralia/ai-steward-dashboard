"""AI Steward Dashboard — policy change monitor.

Six cheap gates in front of one expensive call:

    probe -> validate -> normalise + hash -> diff -> cosmetic gate
          -> fingerprint -> LLM

Everything a document has to survive before it can cost money, or before it
can tell a steward that something changed, lives in `steward/`. This module
sequences those gates, keeps the per-document state in hashes.json, and writes
the artefacts the dashboard reads.
"""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import shutil
import sys
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from steward import (
    PIPELINE_VERSION,
    analysis as llm,
    configure_logging,
    content,
    diffing,
    fetching,
    health,
    history,
    monitor,
    runlog,
    store,
    web,
)
from steward.config import ConfigError, load_config
from steward.monitor import (
    BASELINE_OUTCOMES,
    DOC_CHANGED,
    DOC_FETCH_FAILED,
    DOC_NEW,
    DOC_REBASELINED,
    DOC_REVERTED,
    DOC_SUSPECT,
    HEALTHY_OUTCOMES,
)

# --- Paths -----------------------------------------------------------------

POLICY_SETS_FILE = "policy_sets.json"
HASHES_FILE = "hashes.json"
SNAPSHOTS_DIR = "snapshots"
ANALYSIS_DIR = "analysis"
DIFFS_DIR = "diffs"
LOG_DIR = "logs"

AEST_TZ = timezone(timedelta(hours=10))

# Window for the per-source activity summary shown on the dashboard.
ACTIVITY_DAYS = 30

# hashes.json and the analysis files have always been written with this
# indent; keeping it keeps their diffs readable.
JSON_INDENT = 4

log = logging.getLogger("steward")


# --- Small helpers ---------------------------------------------------------


def setup_directories() -> None:
    for path in (SNAPSHOTS_DIR, ANALYSIS_DIR, DIFFS_DIR, LOG_DIR):
        os.makedirs(path, exist_ok=True)


def slugify_set_name(name: str) -> str:
    return content.set_file_id(name)


def document_snapshot_path(file_id: str, doc_id: str) -> str:
    return os.path.join(SNAPSHOTS_DIR, file_id, f"{doc_id}.txt")


def aggregate_snapshot_path(file_id: str) -> str:
    return os.path.join(SNAPSHOTS_DIR, f"{file_id}.txt")


def diff_path(file_id: str) -> str:
    return os.path.join(DIFFS_DIR, f"{file_id}.diff")


def analysis_path(file_id: str) -> str:
    return os.path.join(ANALYSIS_DIR, f"{file_id}.json")


def rollup_hash(document_hashes: List[str]) -> str:
    """Set-level hash, rolled up from the per-document hashes."""
    joined = "\n".join(document_hashes)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def archive_previous_version(file_id: str, timestamp: str) -> None:
    """Copy the current analysis, snapshot and diff into logs/ before replacing.

    Named by file_id, matching the 500+ archives already on disk and the
    filename grammar history.build_index parses. The previous implementation
    passed file_id where a set name was expected; the parameter is gone rather
    than corrected, because introducing set names here would break both.
    """
    stamp = _stamp(timestamp)
    for source, suffix in (
        (analysis_path(file_id), "analysis.json"),
        (aggregate_snapshot_path(file_id), "snapshot.txt"),
        (diff_path(file_id), "diff.txt"),
    ):
        if os.path.exists(source):
            shutil.copy(source, os.path.join(LOG_DIR, f"{file_id}_{stamp}_{suffix}"))


def validate_policy_sets(policy_sets: list) -> list:
    valid = []
    seen_names: set[str] = set()
    for i, ps in enumerate(policy_sets):
        if not isinstance(ps, dict):
            log.warning("Skipping policy_sets[%d]: not a dict", i)
            continue
        name = ps.get("setName")
        if not name:
            log.warning("Skipping policy_sets[%d]: missing 'setName'", i)
            continue
        if name in seen_names:
            log.warning("Skipping policy_sets[%d] (%s): duplicate setName", i, name)
            continue
        if not ps.get("category"):
            log.warning("Skipping policy_sets[%d] (%s): missing 'category'", i, name)
            continue
        urls = ps.get("urls")
        if not isinstance(urls, list) or not urls:
            log.warning("Skipping policy_sets[%d] (%s): missing or empty 'urls'", i, name)
            continue
        if not all(isinstance(u, dict) and u.get("url") for u in urls):
            log.warning("Skipping policy_sets[%d] (%s): malformed url entry", i, name)
            continue
        # The dashboard renders these as links, so a javascript: or data: URL
        # here would become a clickable script, not just a failed fetch.
        if not all(fetching.is_safe_url(u["url"]) for u in urls):
            log.warning("Skipping policy_sets[%d] (%s): every url must be http(s)", i, name)
            continue
        seen_names.add(name)
        valid.append(ps)
    return valid


# --- Migration -------------------------------------------------------------


def seed_documents_from_legacy(policy_set: dict, file_id: str, cfg) -> Dict[str, dict]:
    """Split a pre-upgrade aggregate snapshot into per-document baselines.

    hashes.json used to hold one MD5 over every URL in a set concatenated
    together, which is why one URL failing looked like the whole set changed.
    The aggregate snapshots are still on disk and still sectioned by URL, so
    the per-document baselines can be recovered rather than thrown away.
    """
    aggregate = store.read_text(aggregate_snapshot_path(file_id))
    sections = content.split_aggregate(aggregate)
    if not sections:
        return {}

    seeded: Dict[str, dict] = {}
    for url_data in policy_set["urls"]:
        url = url_data["url"]
        if url not in sections:
            continue
        doc_id = content.document_id(url)
        text = content.normalise(sections[url], cfg.noise_patterns_for(content.host_of(url)))
        if not text:
            continue
        store.write_text(document_snapshot_path(file_id, doc_id), text)
        seeded[url] = {
            "doc_id": doc_id,
            "label": content.document_label(url_data),
            "hash": content.content_hash(text),
            "length": len(text),
            # Deliberately marked as the previous pipeline: the text came from
            # a different extractor, so the first comparison against it is a
            # re-baseline rather than a change.
            "pipeline_version": PIPELINE_VERSION - 1,
            "extractor": "legacy",
            "consecutive_failures": 0,
        }

    if seeded:
        log.info("  Seeded %d document baseline(s) from the legacy aggregate snapshot", len(seeded))
    return seeded


# --- Per-document processing ----------------------------------------------


def process_document(
    url_data: dict,
    policy_set: dict,
    file_id: str,
    prior: dict,
    cfg,
    timestamp: str,
    session: Optional[fetching.FetchSession] = None,
) -> Tuple[dict, str, Optional[diffing.DiffResult], str]:
    """One policy document through every gate, against its stored snapshot.

    Nothing is written here — the caller decides what to keep. Returns
    (record, outcome, diff_or_None, current_text).
    """
    doc_id = prior.get("doc_id") or content.document_id(url_data["url"])
    return monitor.check_document(
        url_data,
        prior,
        cfg,
        timestamp,
        stored_text=store.read_text(document_snapshot_path(file_id, doc_id)),
        policy_set=policy_set,
        session=session,
    )


# --- Per-set processing ----------------------------------------------------


@dataclass
class SetCheck:
    """What checking every document in one set found."""

    documents: Dict[str, dict] = field(default_factory=dict)
    outcomes: Dict[str, str] = field(default_factory=dict)
    sections: List[Tuple[str, str]] = field(default_factory=list)
    changed: List[Tuple[str, diffing.DiffResult]] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)
    texts_to_write: List[Tuple[str, str]] = field(default_factory=list)

    @property
    def all_ok(self) -> bool:
        return all(outcome in HEALTHY_OUTCOMES for outcome in self.outcomes.values())

    @property
    def any_failed(self) -> bool:
        return any(outcome in (DOC_FETCH_FAILED, DOC_SUSPECT) for outcome in self.outcomes.values())

    @property
    def readable(self) -> bool:
        return any(outcome in HEALTHY_OUTCOMES for outcome in self.outcomes.values())

    def labels_with(self, outcome: str) -> List[str]:
        return [self.documents[url]["label"] for url, o in self.outcomes.items() if o == outcome]


def process_policy_set(
    policy_set: dict,
    previous_entry: dict,
    cfg,
    run_log: runlog.RunLog,
    dry_run: bool,
    session: Optional[fetching.FetchSession] = None,
) -> dict:
    set_name = policy_set["setName"]
    file_id = slugify_set_name(set_name)
    timestamp = datetime.now(AEST_TZ).isoformat()
    log.info("Processing policy set: %s", set_name)

    prior_documents: Dict[str, dict] = previous_entry.get("documents") or {}
    if not prior_documents and previous_entry.get("hash"):
        prior_documents = seed_documents_from_legacy(policy_set, file_id, cfg)

    check = _check_documents(policy_set, file_id, prior_documents, cfg, timestamp, run_log, session)

    entry: Dict[str, Any] = {
        "hash": rollup_hash([check.documents[u].get("hash", "") for u in sorted(check.documents)]),
        "category": policy_set["category"],
        "urls": policy_set["urls"],
        "file_id": file_id,
        "last_checked": timestamp,
        "last_amended": previous_entry.get("last_amended"),
        "last_priority": previous_entry.get("last_priority"),
        "last_verdict": previous_entry.get("last_verdict"),
        "last_change": previous_entry.get("last_change"),
        "last_review": previous_entry.get("last_review"),
        "schema_failures": int(previous_entry.get("schema_failures", 0) or 0),
        "consecutive_failures": (
            int(previous_entry.get("consecutive_failures", 0) or 0) + 1 if check.any_failed else 0
        ),
        "last_success": timestamp if check.all_ok else previous_entry.get("last_success"),
        "documents": check.documents,
    }
    entry["status"] = health.set_status(check.documents, cfg.health.consecutive_failure_threshold)

    if not check.readable:
        log.warning("  No document in '%s' could be read — carrying the previous state forward", set_name)
        return entry

    # Nothing survived to the diff stage: either genuinely unchanged, or a
    # re-baseline, or a first capture. None of those is a policy amendment.
    if not check.changed:
        if dry_run:
            if check.texts_to_write:
                log.info("  [dry-run] Would record %d baseline(s)", len(check.texts_to_write))
            return previous_entry or entry
        _record_baselines(set_name, file_id, previous_entry, entry, check, timestamp)
        return entry

    return _analyse_change(set_name, file_id, previous_entry, prior_documents, entry, check, cfg, run_log, dry_run, timestamp)


def _check_documents(
    policy_set: dict,
    file_id: str,
    prior_documents: Dict[str, dict],
    cfg,
    timestamp: str,
    run_log: runlog.RunLog,
    session: Optional[fetching.FetchSession],
) -> SetCheck:
    set_name = policy_set["setName"]
    check = SetCheck()
    for url_data in policy_set["urls"]:
        url = url_data["url"]
        prior = prior_documents.get(url, {})
        try:
            record, outcome, diff, text = process_document(url_data, policy_set, file_id, prior, cfg, timestamp, session)
        except Exception as exc:  # noqa: BLE001 — one broken page must not cost the rest of the set
            log.exception("    Unhandled error checking %s", url)
            record = monitor.failed_document(url_data, prior, timestamp, web.describe_error(exc))
            outcome, diff = DOC_FETCH_FAILED, None
            text = store.read_text(document_snapshot_path(file_id, record["doc_id"]))
        check.documents[url] = record
        check.outcomes[url] = outcome
        check.sections.append((url, text))

        if outcome in BASELINE_OUTCOMES:
            check.texts_to_write.append((document_snapshot_path(file_id, record["doc_id"]), text))
        if diff is not None:
            check.changed.append((record["label"], diff))
            check.tags.extend(diff.tags)

        run_log.record(
            timestamp=timestamp,
            set_name=set_name,
            file_id=file_id,
            url=url,
            label=record["label"],
            outcome=outcome,
            http_status=record.get("http_status"),
            length=record.get("length"),
            diff_added=record.get("diff_added", 0) if outcome == DOC_CHANGED else 0,
            diff_removed=record.get("diff_removed", 0) if outcome == DOC_CHANGED else 0,
            tags=sorted(set(diff.tags)) if diff else [],
            error=record.get("last_error", ""),
            fetch_ms=record.get("fetch_ms", 0),
            llm_called=False,
        )
    return check


def _record_baselines(
    set_name: str, file_id: str, previous_entry: dict, entry: Dict[str, Any], check: SetCheck, timestamp: str
) -> None:
    """Store new baselines and say why nothing was analysed."""
    _commit_texts(check.texts_to_write)
    _write_aggregate(file_id, check.sections)
    new_docs = check.labels_with(DOC_NEW)
    rebaselined = check.labels_with(DOC_REBASELINED)
    reverted = check.labels_with(DOC_REVERTED)

    if new_docs and not previous_entry.get("hash"):
        log.info("  First scan for '%s'", set_name)
        entry["last_amended"] = timestamp
        entry["last_priority"] = "low"
        entry["last_verdict"] = llm.NO_MATERIAL_CHANGE
        store.save_json(
            {
                "verdict": llm.NO_MATERIAL_CHANGE,
                "summary": "Initial snapshot captured.",
                "analysis": (
                    f"This is the first time the '{set_name}' policy set has been "
                    "monitored. Future runs will compare against this baseline."
                ),
                "priority": "low",
                "date_time": timestamp,
                "changed_documents": [],
            },
            analysis_path(file_id),
            indent=JSON_INDENT,
        )
    elif reverted:
        noted = ", ".join(reverted)
        log.info("  '%s': %s returned to a previously seen version", set_name, noted)
        entry["last_review"] = {
            "timestamp": timestamp,
            "verdict": "reverted",
            "summary": (
                f"{noted} returned to a version already recorded, so it was not "
                "re-analysed. A source that alternates like this is usually serving "
                "two variants rather than being amended."
            ),
            "changed_documents": reverted,
        }
    elif new_docs or rebaselined:
        noted = ", ".join(new_docs + rebaselined)
        log.info("  Baselines recorded for '%s' (%s) — no change reported", set_name, noted)
        entry["last_review"] = {
            "timestamp": timestamp,
            "verdict": "rebaselined",
            "summary": f"Baseline re-recorded for: {noted}. No change reported.",
        }
    else:
        log.info("  No changes detected for '%s'", set_name)


def _analyse_change(
    set_name: str,
    file_id: str,
    previous_entry: dict,
    prior_documents: Dict[str, dict],
    entry: Dict[str, Any],
    check: SetCheck,
    cfg,
    run_log: runlog.RunLog,
    dry_run: bool,
    timestamp: str,
) -> dict:
    """Stage 3 — one diff artefact, one model call, and what to keep."""
    combined_diff = diffing.combine_diffs(check.changed)
    changed_labels = [label for label, _ in check.changed]
    unique_tags = sorted(set(check.tags))
    total_added = sum(d.added for _, d in check.changed)
    total_removed = sum(d.removed for _, d in check.changed)

    log.info(
        "  Change detected in %s (+%d / -%d lines)%s",
        ", ".join(changed_labels),
        total_added,
        total_removed,
        f", tags: {', '.join(unique_tags)}" if unique_tags else "",
    )

    if dry_run:
        log.info("  [dry-run] Skipping analysis and leaving stored state untouched")
        return previous_entry or entry

    analysis = llm.analyse_change(
        set_name,
        combined_diff,
        model=cfg.model,
        changed_documents=changed_labels,
        tags=unique_tags,
    )

    run_log.record(
        timestamp=timestamp,
        set_name=set_name,
        file_id=file_id,
        url="",
        label="(policy set)",
        outcome="analysed" if analysis.ok else ("api_unavailable" if analysis.unavailable else "schema_failed"),
        diff_added=total_added,
        diff_removed=total_removed,
        tags=unique_tags,
        llm_called=True,
        llm_attempts=analysis.attempts,
        prompt_tokens=analysis.prompt_tokens,
        output_tokens=analysis.output_tokens,
        verdict=(analysis.result or {}).get("verdict"),
        priority=(analysis.result or {}).get("priority"),
        error=analysis.error,
    )

    if analysis.result is None:
        # Nothing is stored: the stored snapshot stays put so the same diff is
        # retried next run rather than being silently lost. An overloaded
        # model is not the model misbehaving, so only a real schema failure
        # counts towards the schema alert.
        if analysis.unavailable:
            log.error("  Model unavailable for '%s' — the change will be retried next run", set_name)
        else:
            log.error("  Analysis of '%s' failed schema validation twice — skipping", set_name)
            entry["schema_failures"] = entry["schema_failures"] + 1
        entry["hash"] = previous_entry.get("hash", entry["hash"])
        entry["documents"] = _revert_changed_documents(check.documents, prior_documents, check.outcomes)
        return entry

    entry["schema_failures"] = 0
    result = analysis.result
    verdict = result["verdict"]

    _commit_texts(check.texts_to_write)
    _write_aggregate(file_id, check.sections)
    store.write_text(diff_path(file_id), combined_diff)

    # Where the changed text came from, when it was not the live page, so a
    # change first seen in an Internet Archive capture can be told apart.
    archived = sorted(
        check.documents[url]["label"]
        for url, outcome in check.outcomes.items()
        if outcome == DOC_CHANGED and check.documents[url].get("route") == fetching.ROUTE_ARCHIVE
    )
    provenance = {"archived_documents": archived} if archived else {}

    change_record = {
        "timestamp": timestamp,
        "verdict": verdict,
        "summary": result["summary"],
        "changed_documents": changed_labels,
        "added": total_added,
        "removed": total_removed,
        "tags": unique_tags,
        **provenance,
    }

    if verdict == llm.NO_MATERIAL_CHANGE:
        # The model was allowed to decline, and did. The new text is now the
        # baseline so the same diff is not re-analysed tomorrow, but the set is
        # not badged and last_amended does not move.
        log.info("  Model reports no material change for '%s' — not badging the set", set_name)
        entry["last_review"] = {
            "timestamp": timestamp,
            "verdict": verdict,
            "summary": result["summary"],
            "changed_documents": changed_labels,
        }
        archive_previous_version(file_id, timestamp)
        store.save_json(
            {**result, "date_time": timestamp, "changed_documents": changed_labels, **provenance},
            os.path.join(LOG_DIR, f"{file_id}_{_stamp(timestamp)}_analysis.json"),
            indent=JSON_INDENT,
        )
        return entry

    archive_previous_version(file_id, previous_entry.get("last_checked") or timestamp)
    store.save_json(
        {
            "verdict": verdict,
            "summary": result["summary"],
            "analysis": result["analysis"],
            "priority": result["priority"],
            # Stamped here, in code. The model does not know what time it is.
            "date_time": timestamp,
            "changed_documents": changed_labels,
            "diff_stats": {"added": total_added, "removed": total_removed},
            "fingerprint": unique_tags,
            **provenance,
        },
        analysis_path(file_id),
        indent=JSON_INDENT,
    )

    entry["last_amended"] = timestamp
    entry["last_priority"] = result["priority"]
    entry["last_verdict"] = verdict
    entry["last_change"] = change_record
    entry["last_review"] = {
        "timestamp": timestamp,
        "verdict": verdict,
        "summary": result["summary"],
        "changed_documents": changed_labels,
    }
    log.info("  Analysis complete — verdict: %s, priority: %s", verdict, result["priority"])
    return entry


def stored_documents(hashes: Dict[str, Any]) -> List[Tuple[str, dict]]:
    """Every (url, record) pair held in hashes.json."""
    return [
        (url, record)
        for entry in hashes.values()
        if isinstance(entry, dict)
        for url, record in (entry.get("documents") or {}).items()
        if isinstance(record, dict)
    ]


def _stamp(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        return datetime.now(AEST_TZ).strftime("%Y%m%d_%H%M%S")


def _commit_texts(pending: List[Tuple[str, str]]) -> None:
    for path, text in pending:
        store.write_text(path, text)


def _write_aggregate(file_id: str, sections: List[Tuple[str, str]]) -> None:
    """The combined snapshot the detail page still offers as a disclosure."""
    store.write_text(aggregate_snapshot_path(file_id), content.build_aggregate(sections))


def _revert_changed_documents(
    documents: Dict[str, dict], prior: Dict[str, dict], outcomes: Dict[str, str]
) -> Dict[str, dict]:
    """Keep health fields but restore the prior hash for unanalysed changes."""
    reverted = {}
    for url, record in documents.items():
        if outcomes.get(url) == DOC_CHANGED and url in prior:
            merged = dict(record)
            merged["hash"] = prior[url].get("hash", record.get("hash"))
            merged["length"] = prior[url].get("length", record.get("length"))
            merged["previous_hashes"] = prior[url].get("previous_hashes", [])
            merged["status"] = "analysis_pending"
            reverted[url] = merged
        else:
            reverted[url] = record
    return reverted


# --- Entry point -----------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check monitored policy sets for changes.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run every gate, report what would happen, and change nothing on disk.",
    )
    parser.add_argument(
        "--config",
        default="steward_config.yaml",
        help="Path to the config file (default: steward_config.yaml).",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=None,
        metavar="SET_NAME",
        help="Limit the run to the named policy set. Repeatable. Implies --skip-news and --skip-transparency.",
    )
    parser.add_argument(
        "--skip-news",
        action="store_true",
        help="Leave the news and incident feed alone.",
    )
    parser.add_argument(
        "--skip-transparency",
        action="store_true",
        help="Leave the AI transparency statements alone.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    configure_logging()
    args = parse_args(argv)
    setup_directories()

    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("Configuration error — %s", exc)
        return 1

    if not args.dry_run and not os.environ.get("GEMINI_API_KEY"):
        log.error("GEMINI_API_KEY is not set. Exiting.")
        return 1

    try:
        return run(cfg, args)
    except store.StateError as exc:
        log.error("Stopping without writing anything: %s", exc)
        return 1


def run(cfg, args: argparse.Namespace) -> int:
    policy_sets = store.load_json(POLICY_SETS_FILE, [])
    if not isinstance(policy_sets, list):
        log.error("%s must contain a JSON array. Exiting.", POLICY_SETS_FILE)
        return 1

    configured_names = {ps.get("setName") for ps in policy_sets if isinstance(ps, dict)}
    policy_sets = validate_policy_sets(policy_sets)
    if args.only:
        wanted = set(args.only)
        policy_sets = [ps for ps in policy_sets if ps["setName"] in wanted]
    if not policy_sets:
        log.error("No valid policy sets to check. Exiting.")
        return 1

    previous_hashes = store.load_json(HASHES_FILE, {})
    if not isinstance(previous_hashes, dict):
        raise store.StateError(f"{HASHES_FILE} must contain a JSON object")

    run_id = uuid.uuid4().hex[:12]
    run_log = runlog.RunLog(run_id)
    log.info("Run %s starting — %d policy set(s)%s", run_id, len(policy_sets), " [dry-run]" if args.dry_run else "")

    session = fetching.FetchSession.remembering(
        stored_documents(previous_hashes), cfg.fetch.blocked_host_recheck_days
    )
    current_hashes: Dict[str, Any] = {}
    try:
        for policy_set in policy_sets:
            set_name = policy_set["setName"]
            try:
                current_hashes[set_name] = process_policy_set(
                    policy_set, previous_hashes.get(set_name, {}), cfg, run_log, args.dry_run, session
                )
            except Exception as exc:  # noqa: BLE001 — one bad source must not lose the run
                log.exception("Unhandled error processing '%s': %s", set_name, exc)
                if set_name in previous_hashes:
                    current_hashes[set_name] = previous_hashes[set_name]
    finally:
        session.close()

    # Sets that were skipped this run (--only, or a malformed entry) keep
    # their stored state rather than vanishing from the dashboard. A set
    # removed from policy_sets.json is dropped.
    for set_name, entry in previous_hashes.items():
        if set_name in configured_names:
            current_hashes.setdefault(set_name, entry)

    report = health.build_report(current_hashes, cfg, runlog.error_rate(run_log.records))

    if args.dry_run:
        _report_dry_run(run_log, report)
        return _run_streams(cfg, args)

    store.save_json(current_hashes, HASHES_FILE, indent=JSON_INDENT)
    run_log.flush(cfg.retention.run_log_days)
    report["activity_days"] = ACTIVITY_DAYS
    recent_records = runlog.load_records(days=ACTIVITY_DAYS)
    report["activity"] = runlog.activity_summary(recent_records)
    report["activity_daily"] = runlog.daily_summary(recent_records)
    health.write_report(report)
    if health.write_alert(report):
        log.warning("Health alerts raised: %d — see %s", len(report["alerts"]), health.ALERT_FILE)
    else:
        store.remove(health.ALERT_FILE)

    pruned = history.prune(LOG_DIR, cfg.retention.log_days)
    if pruned:
        log.info("Pruned %d archived file(s) past %d-day retention", pruned, cfg.retention.log_days)

    known = {entry["file_id"] for entry in current_hashes.values() if entry.get("file_id")}
    history.write_index(history.build_index(LOG_DIR, known))

    totals = run_log.token_totals()
    log.info(
        "Run %s complete — outcomes: %s; %d model call(s), %d prompt / %d output tokens; health: %s",
        run_id,
        run_log.counts_by_outcome(),
        totals["llm_calls"],
        totals["prompt_tokens"],
        totals["output_tokens"],
        report["overall"],
    )
    return _run_streams(cfg, args)


def _run_streams(cfg, args: argparse.Namespace) -> int:
    """The transparency statements and the news feed, after the policy check.

    Imported here rather than at the top so a policy-only run never loads
    them, and isolated so a failure in one cannot touch what the policy run
    or the other stream wrote.
    """
    if args.only:
        return 0
    status = 0
    if not args.skip_transparency:
        try:
            import transparency_watch

            status = max(status, transparency_watch.run(cfg, dry_run=args.dry_run))
        except Exception as exc:  # noqa: BLE001 — the policy results are already saved
            log.exception("Transparency run failed: %s", exc)
            status = 1
    if not args.skip_news:
        try:
            import news_watch

            status = max(status, news_watch.run(cfg, dry_run=args.dry_run))
        except Exception as exc:  # noqa: BLE001 — the policy results are already saved
            log.exception("News run failed: %s", exc)
            status = 1
    return status


def _report_dry_run(run_log: runlog.RunLog, report: Dict[str, Any]) -> None:
    log.info("--- dry run summary ---")
    for outcome, count in sorted(run_log.counts_by_outcome().items()):
        log.info("  %-16s %d", outcome, count)
    log.info("  overall health: %s", report["overall"])
    for alert in report.get("alerts", []):
        log.info("  alert: %s %s %s", alert["kind"], alert.get("set_name"), alert.get("detail"))
    log.info("Nothing was written to disk.")


if __name__ == "__main__":
    sys.exit(main())
