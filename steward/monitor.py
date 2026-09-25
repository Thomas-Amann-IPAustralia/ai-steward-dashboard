"""One document through every gate: the part of a check that both streams share.

The policy monitor (main.py) and the transparency watcher
(transparency_watch.py) put every document they follow through the same
sequence — fetch, validate, normalise and hash, compare with the stored
baseline, diff, cosmetic gate — before anything can reach the model. That
sequence lives here so neither orchestrator has to import the other.

Nothing here writes a file. The caller reads the stored baseline, passes it
in, and decides what to keep from the result.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from . import PIPELINE_VERSION, content, diffing, fetching
from .validation import validate_capture

log = logging.getLogger(__name__)

# Per-document outcomes recorded in hashes.json and runs.jsonl.
DOC_UNCHANGED = "unchanged"
DOC_NOT_MODIFIED = "not_modified"
DOC_CHANGED = "changed"
DOC_NEW = "new"
DOC_REBASELINED = "rebaselined"
DOC_SUSPECT = "suspect_scrape"
DOC_FETCH_FAILED = "fetch_failed"
# The text moved but said nothing new: re-typeset, re-wrapped, re-linked.
DOC_COSMETIC = "cosmetic"
# The text returned to a version already seen — the flip-flop a CDN serving
# two variants, or an A/B test, produces day after day.
DOC_REVERTED = "reverted"

HEALTHY_OUTCOMES = {
    DOC_UNCHANGED,
    DOC_NOT_MODIFIED,
    DOC_CHANGED,
    DOC_NEW,
    DOC_REBASELINED,
    DOC_COSMETIC,
    DOC_REVERTED,
}
# Outcomes whose captured text becomes the stored baseline.
BASELINE_OUTCOMES = {DOC_CHANGED, DOC_NEW, DOC_REBASELINED, DOC_COSMETIC, DOC_REVERTED}


def check_document(
    url_data: dict,
    prior: dict,
    cfg,
    timestamp: str,
    *,
    stored_text: str,
    policy_set: Optional[dict] = None,
    session: Optional[fetching.FetchSession] = None,
) -> Tuple[dict, str, Optional[diffing.DiffResult], str]:
    """Run one document through every gate.

    `stored_text` is the baseline to compare against. Returns (record,
    outcome, diff_or_None, current_text).
    """
    url = url_data["url"]
    doc_id = prior.get("doc_id") or content.document_id(url)
    label = content.document_label(url_data)

    record = dict(prior)
    record.update({"doc_id": doc_id, "label": label, "last_checked": timestamp})
    record.setdefault("consecutive_failures", 0)

    result = fetching.fetch_document(url_data, prior, cfg, policy_set, session=session)
    record["http_status"] = result.http_status
    record["fetch_ms"] = result.duration_ms
    record.update(fetch_route_fields(result, prior, timestamp))

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
        log.warning("    Fetch failed for %s: %s", url, result.error)
        return _failed(record, prior, DOC_FETCH_FAILED, result.error), DOC_FETCH_FAILED, None, stored_text

    # A stored baseline that is itself a block page or a stub can never be
    # compared against: the real page would be rejected for "growing" 50-fold
    # and the source would stay failing forever. Digital.gov.au sat in
    # exactly that state behind a 347-character Chrome error page.
    baseline_valid = bool(stored_text) and _is_plausible_capture(stored_text, cfg)
    prior_length = prior.get("length") if baseline_valid else None

    # Stage 2 pass 1 — normalise, then decide whether this is plausibly the
    # document at all. A capture that fails validation never overwrites the
    # stored snapshot and never reaches the model.
    normalised = content.normalise(result.text, cfg.noise_patterns_for(content.host_of(url)))
    verdict = validate_capture(
        normalised,
        prior_length,
        min_length=cfg.validation.min_length,
        shrink_ratio=cfg.validation.shrink_ratio,
        growth_ratio=cfg.validation.growth_ratio,
        failure_signatures=cfg.validation.failure_signatures,
    )
    if not verdict.ok:
        log.warning("    Rejected capture of %s — %s (%s)", url, verdict.reason, verdict.detail)
        record = _failed(record, prior, DOC_SUSPECT, f"{verdict.reason}: {verdict.detail}")
        record["suspect_length"] = len(normalised)
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
    if stale_pipeline or not baseline_valid:
        if stale_pipeline:
            reason = "extraction pipeline changed"
        elif stored_text:
            reason = "stored baseline was not a valid capture"
        else:
            reason = "stored snapshot missing"
        log.info("    Re-baselining %s (%s)", label, reason)
        record["status"] = DOC_REBASELINED
        record["rebaseline_reason"] = reason
        # Versions recorded under different rules are not comparable either.
        record["previous_hashes"] = []
        return record, DOC_REBASELINED, None, normalised

    if new_hash == prior.get("hash"):
        record["status"] = DOC_UNCHANGED
        return record, DOC_UNCHANGED, None, normalised

    remembered = [h for h in prior.get("previous_hashes") or [] if h]
    record["previous_hashes"] = _remember(prior.get("hash"), remembered, new_hash, cfg.diff.revert_memory)

    # Back to a version already seen. Analysing it again would re-report a
    # change the steward has already been shown, in reverse, every time the
    # source flips — so it is recorded, not analysed.
    if new_hash in remembered:
        log.info("    %s returned to a previously seen version — not re-analysed", label)
        record["status"] = DOC_REVERTED
        record["last_changed"] = timestamp
        return record, DOC_REVERTED, None, normalised

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
        log.info(
            "    %s: %d line(s) moved, none substantively — cosmetic, no analysis",
            label,
            diff.cosmetic_lines,
        )
        record["status"] = DOC_COSMETIC
        record["cosmetic_lines"] = diff.cosmetic_lines
        return record, DOC_COSMETIC, None, normalised

    record["status"] = DOC_CHANGED
    record["last_changed"] = timestamp
    record["diff_added"] = diff.added
    record["diff_removed"] = diff.removed
    record["cosmetic_lines"] = diff.cosmetic_lines
    return record, DOC_CHANGED, diff, normalised


def failed_document(url_data: dict, prior: dict, timestamp: str, error: str) -> dict:
    """The record for a document whose check raised instead of returning.

    The prior state is carried forward and the failure counted, exactly as
    for a fetch that failed, so one broken page never costs the rest of a run.
    """
    record = dict(prior)
    record.update(
        {
            "doc_id": prior.get("doc_id") or content.document_id(url_data["url"]),
            "label": content.document_label(url_data),
            "last_checked": timestamp,
        }
    )
    return _failed(record, prior, DOC_FETCH_FAILED, error)


def _failed(record: dict, prior: dict, status: str, error: str) -> dict:
    record.update(
        {
            "status": status,
            "consecutive_failures": int(prior.get("consecutive_failures", 0) or 0) + 1,
            "last_error": error,
        }
    )
    return record


def fetch_route_fields(result: fetching.FetchResult, prior: dict, timestamp: str) -> dict:
    """How the document was reached, kept so the next run can go straight there.

    `plain_blocked_at` is when a plain GET was last refused: refreshed when it
    is refused again, cleared when plain HTTP works, and carried unchanged
    when plain HTTP was skipped because the host was already known to refuse
    it — so it ages out and plain HTTP is retried after
    `fetch.blocked_host_recheck_days`.
    """
    fields: Dict[str, Any] = {}
    if result.route:
        fields["route"] = result.route
    fields["archived_at"] = result.archived_at
    if result.plain_blocked is True:
        fields["plain_blocked_at"] = timestamp
    elif result.plain_blocked is False:
        fields["plain_blocked_at"] = None
    else:
        fields["plain_blocked_at"] = prior.get("plain_blocked_at")
    return fields


def _is_plausible_capture(text: str, cfg) -> bool:
    """Whether stored text passes the absolute checks a fresh capture must."""
    return validate_capture(
        text,
        None,
        min_length=cfg.validation.min_length,
        shrink_ratio=cfg.validation.shrink_ratio,
        growth_ratio=cfg.validation.growth_ratio,
        failure_signatures=cfg.validation.failure_signatures,
    ).ok


def _remember(current: Optional[str], remembered: List[str], incoming: str, limit: int) -> List[str]:
    """Most-recent-first hashes this document has held, excluding the new one."""
    if limit <= 0:
        return []
    history_ = [current] if current else []
    history_.extend(h for h in remembered if h != current)
    return [h for h in history_ if h != incoming][:limit]
