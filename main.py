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
import json
import logging
import os
import re
import shutil
import sys
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from steward import PIPELINE_VERSION, analysis as llm, content, diffing, fetching, health, history, runlog
from steward.config import ConfigError, load_config
from steward.validation import validate_capture

# --- Paths -----------------------------------------------------------------

POLICY_SETS_FILE = "policy_sets.json"
HASHES_FILE = "hashes.json"
SNAPSHOTS_DIR = "snapshots"
ANALYSIS_DIR = "analysis"
DIFFS_DIR = "diffs"
LOG_DIR = "logs"

AEST_TZ = timezone(timedelta(hours=10))

# Per-document outcomes recorded in hashes.json and runs.jsonl.
DOC_UNCHANGED = "unchanged"
DOC_NOT_MODIFIED = "not_modified"
DOC_CHANGED = "changed"
DOC_NEW = "new"
DOC_REBASELINED = "rebaselined"
DOC_SUSPECT = "suspect_scrape"
DOC_FETCH_FAILED = "fetch_failed"

_HEALTHY_OUTCOMES = {DOC_UNCHANGED, DOC_NOT_MODIFIED, DOC_CHANGED, DOC_NEW, DOC_REBASELINED}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("steward")


# --- Small helpers ---------------------------------------------------------


def setup_directories() -> None:
    for path in (SNAPSHOTS_DIR, ANALYSIS_DIR, DIFFS_DIR, LOG_DIR):
        os.makedirs(path, exist_ok=True)


def slugify_set_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9\-]+", "_", name).strip("_")


def load_json_file(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read %s, using default", path)
        return default


def save_json_file(data: Any, path: str) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=4, ensure_ascii=False)


def read_text(path: str) -> str:
    if not os.path.exists(path):
        return ""
    with open(path, "r", encoding="utf-8") as handle:
        return handle.read()


def write_text(path: str, text: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)


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
    try:
        stamp = datetime.fromisoformat(timestamp).strftime("%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        stamp = datetime.now(AEST_TZ).strftime("%Y%m%d_%H%M%S")

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
    aggregate = read_text(aggregate_snapshot_path(file_id))
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
        write_text(document_snapshot_path(file_id, doc_id), text)
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
) -> Tuple[dict, str, Optional[diffing.DiffResult], str]:
    """Run one document through every gate.

    Returns (record, outcome, diff_or_None, current_text).
    """
    url = url_data["url"]
    doc_id = prior.get("doc_id") or content.document_id(url)
    label = content.document_label(url_data)
    stored_text = read_text(document_snapshot_path(file_id, doc_id))

    record = dict(prior)
    record.update({"doc_id": doc_id, "label": label, "last_checked": timestamp})
    record.setdefault("consecutive_failures", 0)

    result = fetching.fetch_document(url_data, prior, cfg, policy_set)
    record["http_status"] = result.http_status
    record["fetch_ms"] = result.duration_ms

    # Stage 1 — the metadata probe answered it.
    if result.status == fetching.NOT_MODIFIED:
        record.update(
            {
                "status": DOC_NOT_MODIFIED,
                "etag": result.etag or prior.get("etag"),
                "last_modified": result.last_modified or prior.get("last_modified"),
                "consecutive_failures": 0,
                "last_success": timestamp,
                "last_error": "",
            }
        )
        return record, DOC_NOT_MODIFIED, None, stored_text

    if result.status == fetching.FAILED:
        record.update(
            {
                "status": DOC_FETCH_FAILED,
                "consecutive_failures": int(prior.get("consecutive_failures", 0)) + 1,
                "last_error": result.error,
            }
        )
        log.warning("    Fetch failed for %s: %s", url, result.error)
        return record, DOC_FETCH_FAILED, None, stored_text

    # Stage 2 pass 1 — normalise, then decide whether this is plausibly the
    # document at all. A capture that fails validation never overwrites the
    # stored snapshot and never reaches the model.
    normalised = content.normalise(result.text, cfg.noise_patterns_for(content.host_of(url)))
    verdict = validate_capture(
        normalised,
        prior.get("length"),
        min_length=cfg.validation.min_length,
        shrink_ratio=cfg.validation.shrink_ratio,
        growth_ratio=cfg.validation.growth_ratio,
        failure_signatures=cfg.validation.failure_signatures,
    )
    if not verdict.ok:
        record.update(
            {
                "status": DOC_SUSPECT,
                "consecutive_failures": int(prior.get("consecutive_failures", 0)) + 1,
                "last_error": f"{verdict.reason}: {verdict.detail}",
                "suspect_length": len(normalised),
            }
        )
        log.warning("    Rejected capture of %s — %s (%s)", url, verdict.reason, verdict.detail)
        return record, DOC_SUSPECT, None, stored_text

    new_hash = content.content_hash(normalised)
    record.update(
        {
            "hash": new_hash,
            "length": len(normalised),
            "etag": result.etag,
            "last_modified": result.last_modified,
            "extractor": result.extractor,
            "pipeline_version": PIPELINE_VERSION,
            "consecutive_failures": 0,
            "last_success": timestamp,
            "last_error": "",
        }
    )

    # First time this document has ever been read.
    if not prior.get("hash"):
        record["status"] = DOC_NEW
        record["last_changed"] = timestamp
        return record, DOC_NEW, None, normalised

    # The extractor or the normalisation rules changed underneath the stored
    # baseline, so the two are not comparable. Re-baseline and say so, rather
    # than reporting a change that did not happen.
    stale_pipeline = int(prior.get("pipeline_version", 0)) != PIPELINE_VERSION
    if stale_pipeline or not stored_text:
        reason = "extraction pipeline changed" if stale_pipeline else "stored snapshot missing"
        log.info("    Re-baselining %s (%s)", label, reason)
        record["status"] = DOC_REBASELINED
        record["rebaseline_reason"] = reason
        return record, DOC_REBASELINED, None, normalised

    if new_hash == prior.get("hash"):
        record["status"] = DOC_UNCHANGED
        return record, DOC_UNCHANGED, None, normalised

    # Stage 2 pass 2 — the diff, and the cosmetic gate.
    diff = diffing.compute_diff(
        stored_text,
        normalised,
        label=label,
        context_lines=cfg.diff.context_lines,
        max_chars=cfg.diff.max_diff_chars,
        watchlist=cfg.fingerprint.watchlist,
    )
    if diff.is_empty:
        log.info("    %s: hash moved but the diff is empty — cosmetic, no analysis", label)
        record["status"] = DOC_UNCHANGED
        return record, DOC_UNCHANGED, None, normalised

    record["status"] = DOC_CHANGED
    record["last_changed"] = timestamp
    record["diff_added"] = diff.added
    record["diff_removed"] = diff.removed
    return record, DOC_CHANGED, diff, normalised


# --- Per-set processing ----------------------------------------------------


def process_policy_set(
    policy_set: dict,
    previous_entry: dict,
    cfg,
    run_log: runlog.RunLog,
    dry_run: bool,
) -> dict:
    set_name = policy_set["setName"]
    file_id = slugify_set_name(set_name)
    timestamp = datetime.now(AEST_TZ).isoformat()
    log.info("Processing policy set: %s", set_name)

    prior_documents: Dict[str, dict] = previous_entry.get("documents") or {}
    if not prior_documents and previous_entry.get("hash"):
        prior_documents = seed_documents_from_legacy(policy_set, file_id, cfg)

    documents: Dict[str, dict] = {}
    sections: List[Tuple[str, str]] = []
    changed: List[Tuple[str, diffing.DiffResult]] = []
    outcomes: Dict[str, str] = {}
    tags: List[str] = []
    texts_to_write: List[Tuple[str, str]] = []

    for url_data in policy_set["urls"]:
        url = url_data["url"]
        record, outcome, diff, text = process_document(
            url_data, policy_set, file_id, prior_documents.get(url, {}), cfg, timestamp
        )
        documents[url] = record
        outcomes[url] = outcome
        sections.append((url, text))

        if outcome in (DOC_CHANGED, DOC_NEW, DOC_REBASELINED):
            texts_to_write.append((document_snapshot_path(file_id, record["doc_id"]), text))
        if diff is not None:
            changed.append((record["label"], diff))
            tags.extend(diff.tags)

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

    all_ok = all(outcome in _HEALTHY_OUTCOMES for outcome in outcomes.values())
    any_failed = any(outcome in (DOC_FETCH_FAILED, DOC_SUSPECT) for outcome in outcomes.values())
    readable = [url for url, outcome in outcomes.items() if outcome in _HEALTHY_OUTCOMES]

    entry: Dict[str, Any] = {
        "hash": rollup_hash([documents[u].get("hash", "") for u in sorted(documents)]),
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
            int(previous_entry.get("consecutive_failures", 0) or 0) + 1 if any_failed else 0
        ),
        "last_success": timestamp if all_ok else previous_entry.get("last_success"),
        "documents": documents,
    }
    entry["status"] = health.set_status(documents, cfg.health.consecutive_failure_threshold)

    if not readable:
        log.warning("  No document in '%s' could be read — carrying the previous state forward", set_name)
        return entry

    # Nothing survived to the diff stage: either genuinely unchanged, or a
    # re-baseline, or a first capture. None of those is a policy amendment.
    if not changed:
        _commit_texts(texts_to_write)
        _write_aggregate(file_id, sections)
        new_docs = [documents[u]["label"] for u, o in outcomes.items() if o == DOC_NEW]
        rebaselined = [documents[u]["label"] for u, o in outcomes.items() if o == DOC_REBASELINED]

        if new_docs and not previous_entry.get("hash"):
            log.info("  First scan for '%s'", set_name)
            entry["last_amended"] = timestamp
            entry["last_priority"] = "low"
            entry["last_verdict"] = llm.NO_MATERIAL_CHANGE
            save_json_file(
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
            )
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
        return entry

    # Stage 3 — one diff artefact, one model call.
    combined_diff = diffing.combine_diffs(changed)
    changed_labels = [label for label, _ in changed]
    unique_tags = sorted(set(tags))
    total_added = sum(d.added for _, d in changed)
    total_removed = sum(d.removed for _, d in changed)

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

    outcome = llm.analyse_change(
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
        outcome="analysed" if outcome.ok else "schema_failed",
        diff_added=total_added,
        diff_removed=total_removed,
        tags=unique_tags,
        llm_called=True,
        llm_attempts=outcome.attempts,
        prompt_tokens=outcome.prompt_tokens,
        output_tokens=outcome.output_tokens,
        verdict=(outcome.result or {}).get("verdict"),
        priority=(outcome.result or {}).get("priority"),
        error=outcome.error,
    )

    if not outcome.ok:
        # Nothing is stored: the stored snapshot stays put so the same diff is
        # retried next run rather than being silently lost.
        log.error("  Analysis of '%s' failed schema validation twice — skipping", set_name)
        entry["schema_failures"] = entry["schema_failures"] + 1
        entry["hash"] = previous_entry.get("hash", entry["hash"])
        entry["documents"] = _revert_changed_documents(documents, prior_documents, outcomes)
        return entry

    entry["schema_failures"] = 0
    result = outcome.result
    verdict = result["verdict"]

    _commit_texts(texts_to_write)
    _write_aggregate(file_id, sections)
    write_text(diff_path(file_id), combined_diff)

    change_record = {
        "timestamp": timestamp,
        "verdict": verdict,
        "changed_documents": changed_labels,
        "added": total_added,
        "removed": total_removed,
        "tags": unique_tags,
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
        save_json_file(
            {**result, "date_time": timestamp, "changed_documents": changed_labels},
            os.path.join(LOG_DIR, f"{file_id}_{_stamp(timestamp)}_analysis.json"),
        )
        return entry

    archive_previous_version(file_id, previous_entry.get("last_checked") or timestamp)
    save_json_file(
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
        },
        analysis_path(file_id),
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


def _stamp(timestamp: str) -> str:
    try:
        return datetime.fromisoformat(timestamp).strftime("%Y%m%d_%H%M%S")
    except (TypeError, ValueError):
        return datetime.now(AEST_TZ).strftime("%Y%m%d_%H%M%S")


def _commit_texts(pending: List[Tuple[str, str]]) -> None:
    for path, text in pending:
        write_text(path, text)


def _write_aggregate(file_id: str, sections: List[Tuple[str, str]]) -> None:
    """The combined snapshot the detail page still offers as a disclosure."""
    write_text(aggregate_snapshot_path(file_id), content.build_aggregate(sections))


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
        help="Limit the run to the named policy set. Repeatable.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
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

    policy_sets = load_json_file(POLICY_SETS_FILE, [])
    if not isinstance(policy_sets, list):
        log.error("%s must contain a JSON array. Exiting.", POLICY_SETS_FILE)
        return 1

    policy_sets = validate_policy_sets(policy_sets)
    if args.only:
        wanted = set(args.only)
        policy_sets = [ps for ps in policy_sets if ps["setName"] in wanted]
    if not policy_sets:
        log.error("No valid policy sets to check. Exiting.")
        return 1

    previous_hashes = load_json_file(HASHES_FILE, {})
    if not isinstance(previous_hashes, dict):
        previous_hashes = {}

    run_id = uuid.uuid4().hex[:12]
    run_log = runlog.RunLog(run_id)
    log.info("Run %s starting — %d policy set(s)%s", run_id, len(policy_sets), " [dry-run]" if args.dry_run else "")

    current_hashes: Dict[str, Any] = {}
    for policy_set in policy_sets:
        set_name = policy_set["setName"]
        try:
            current_hashes[set_name] = process_policy_set(
                policy_set, previous_hashes.get(set_name, {}), cfg, run_log, args.dry_run
            )
        except Exception as exc:  # noqa: BLE001 — one bad source must not lose the run
            log.exception("Unhandled error processing '%s': %s", set_name, exc)
            if set_name in previous_hashes:
                current_hashes[set_name] = previous_hashes[set_name]

    # Sets that were skipped this run keep their stored state rather than
    # vanishing from the dashboard.
    for set_name, entry in previous_hashes.items():
        current_hashes.setdefault(set_name, entry)

    report = health.build_report(current_hashes, cfg, runlog.error_rate(run_log.records))

    if args.dry_run:
        _report_dry_run(run_log, report)
        return 0

    save_json_file(current_hashes, HASHES_FILE)
    health.write_report(report)
    if health.write_alert(report):
        log.warning("Health alerts raised: %d — see %s", len(report["alerts"]), health.ALERT_FILE)
    elif os.path.exists(health.ALERT_FILE):
        os.remove(health.ALERT_FILE)

    pruned = history.prune(LOG_DIR, cfg.retention.log_days)
    if pruned:
        log.info("Pruned %d archived file(s) past %d-day retention", pruned, cfg.retention.log_days)

    known = {entry["file_id"] for entry in current_hashes.values() if entry.get("file_id")}
    history.write_index(history.build_index(LOG_DIR, known))

    run_log.flush(cfg.retention.run_log_days)

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
    return 0


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
