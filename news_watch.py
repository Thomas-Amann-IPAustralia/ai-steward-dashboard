"""AI Steward Dashboard — news and AI-incident feed.

The policy monitor answers "did a document I rely on change?". This answers
the question that comes straight after it: "what else happened this week
that I should know about?" — Australian government AI announcements, the
reporting around them, regulators overseas, the providers APS staff use, and
the OECD AI Incidents Monitor.

Same shape as main.py: cheap deterministic gates in `steward/news.py`, one
batched model call per run in `steward/news_enrichment.py`, and this module
the only one that reads and writes files. It runs after the policy check in
`main.py`, or on its own:

    python news_watch.py                 # fetch, gate, enrich, write
    python news_watch.py --dry-run       # everything except writing
    python news_watch.py --only oecd-aim-australia --no-enrich

Outputs:
    news/feed.json            items inside the window, plus per-source health
    news/archive/YYYY-MM.json items that have aged out, by month published
    news/state.json           conditional-GET validators and ids already seen
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

from steward import content, feeds, health, news, news_enrichment
from steward.config import ConfigError, load_config
from steward.fetching import is_safe_url

SOURCES_FILE = "news_sources.json"
POLICY_SETS_FILE = "policy_sets.json"
NEWS_DIR = "news"
FEED_FILE = os.path.join(NEWS_DIR, "feed.json")
STATE_FILE = os.path.join(NEWS_DIR, "state.json")
ARCHIVE_DIR = os.path.join(NEWS_DIR, "archive")

# How far back the model is shown earlier headlines when matching stories.
STORY_DAYS = 10

# Ids are remembered this long past the window, so an item that drops out of
# the feed and reappears in a source is not ingested a second time.
SEEN_GRACE_DAYS = 30

log = logging.getLogger("steward.news")

_SOURCE_ID = re.compile(r"^[a-z0-9][a-z0-9-]{1,60}$")


# --- Files -----------------------------------------------------------------------


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError):
        log.warning("Failed to read %s, using default", path)
        return default


def save_json(data: Any, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
    os.replace(tmp, path)


def validate_sources(sources: Any) -> List[dict]:
    """The usable entries of news_sources.json; anything malformed is skipped
    with a warning naming it, never a crash."""
    if not isinstance(sources, list):
        log.error("%s must contain a JSON array", SOURCES_FILE)
        return []

    valid: List[dict] = []
    seen: set = set()
    for i, source in enumerate(sources):
        where = f"{SOURCES_FILE}[{i}]"
        if not isinstance(source, dict):
            log.warning("Skipping %s: not an object", where)
            continue
        source_id = source.get("id")
        if not isinstance(source_id, str) or not _SOURCE_ID.match(source_id):
            log.warning("Skipping %s: 'id' must be lower-case letters, digits and hyphens", where)
            continue
        if source_id in seen:
            log.warning("Skipping %s (%s): duplicate id", where, source_id)
            continue
        if not source.get("name") or not source.get("category"):
            log.warning("Skipping %s (%s): 'name' and 'category' are required", where, source_id)
            continue
        if source.get("type") not in feeds.SOURCE_TYPES:
            log.warning("Skipping %s (%s): 'type' must be one of %s", where, source_id, feeds.SOURCE_TYPES)
            continue
        if source.get("kind", news.KIND_NEWS) not in news.KINDS:
            log.warning("Skipping %s (%s): 'kind' must be one of %s", where, source_id, news.KINDS)
            continue
        if source["type"] == feeds.TYPE_RSS and not is_safe_url(source.get("url", "")):
            log.warning("Skipping %s (%s): 'url' must be an http(s) URL", where, source_id)
            continue
        if source["type"] == feeds.TYPE_OECD_AIM and not isinstance(source.get("query"), dict):
            log.warning("Skipping %s (%s): an oecd_aim source needs a 'query' object", where, source_id)
            continue
        seen.add(source_id)
        valid.append(source)
    return valid


def append_to_archive(items: Sequence[dict], dry_run: bool) -> int:
    """File aged-out items under the month they were published."""
    by_month: Dict[str, List[dict]] = {}
    for item in items:
        by_month.setdefault(news.archive_month(item), []).append(item)

    written = 0
    for month, month_items in by_month.items():
        path = os.path.join(ARCHIVE_DIR, f"{month}.json")
        archive = load_json(path, {"month": month, "items": []})
        held = {item["id"] for item in archive.get("items", [])}
        fresh = [item for item in month_items if item["id"] not in held]
        if not fresh:
            continue
        archive["items"] = sorted(
            archive.get("items", []) + fresh, key=lambda i: i.get("published", ""), reverse=True
        )
        written += len(fresh)
        if not dry_run:
            save_json(archive, path)
    return written


# --- The run ------------------------------------------------------------------------


def _source_status(failures: int, threshold: int) -> str:
    if failures >= threshold:
        return health.FAILING
    if failures > 0:
        return health.DEGRADED
    return health.OK


def _days_ago(now: datetime, days: int) -> str:
    return (now - timedelta(days=days)).isoformat()


def _vendors(policy_sets: Sequence[dict]) -> List[str]:
    """Provider names for the prompt: the first keyword of each private-sector set."""
    return [
        ps["keywords"][0]
        for ps in policy_sets
        if ps.get("category") == "Private Sector" and ps.get("keywords")
    ]


def run(cfg, *, dry_run: bool = False, only: Optional[Sequence[str]] = None, enrich: bool = True) -> int:
    news_cfg = cfg.news
    if not news_cfg.enabled:
        log.info("News feed disabled in config — skipping")
        return 0

    all_sources = validate_sources(load_json(SOURCES_FILE, []))
    sources = [s for s in all_sources if not only or s["id"] in set(only)]
    if not sources:
        log.error("No valid news sources to check.")
        return 1

    now = news.utc_now()
    timestamp = now.isoformat()
    vocab = news.Vocabulary.from_config(news_cfg)
    policy_sets = [ps for ps in load_json(POLICY_SETS_FILE, []) if isinstance(ps, dict) and ps.get("setName")]
    links = news.policy_links(policy_sets, content.set_file_id)

    state = load_json(STATE_FILE, {})
    source_state: Dict[str, dict] = state.get("sources", {})
    seen: Dict[str, str] = state.get("seen", {})
    feed = load_json(FEED_FILE, {})
    existing: List[dict] = [i for i in feed.get("items", []) if isinstance(i, dict) and i.get("id")]
    held = {item["id"]: item for item in existing}

    log.info("News run starting — %d source(s)%s", len(sources), " [dry-run]" if dry_run else "")

    new_items: List[dict] = []
    dropped: Dict[str, int] = {}
    fetched_ok = 0

    for source in sources:
        prior = dict(source_state.get(source["id"], {}))
        result = feeds.fetch_source(
            source, prior, timeout=cfg.fetch.timeout_seconds, user_agent=cfg.fetch.user_agent
        )
        record = dict(prior)
        record.update({"last_checked": timestamp, "http_status": result.http_status, "fetch_ms": result.duration_ms})

        if not result.ok:
            record["consecutive_failures"] = int(prior.get("consecutive_failures", 0)) + 1
            record["last_error"] = result.error
            source_state[source["id"]] = record
            log.warning("  %-28s failed: %s", source["id"], result.error)
            continue

        fetched_ok += 1
        record.update(
            {
                "consecutive_failures": 0,
                "last_success": timestamp,
                "last_error": "",
                "etag": result.etag or prior.get("etag"),
                "last_modified": result.last_modified or prior.get("last_modified"),
            }
        )
        source_state[source["id"]] = record

        if result.status == feeds.NOT_MODIFIED:
            log.info("  %-28s 304 Not Modified", source["id"])
            continue

        added = 0
        for entry in result.entries:
            item, reason = news.build_item(
                entry, source, now=now, window_days=news_cfg.window_days, vocab=vocab, links=links
            )
            if item is None:
                dropped[reason] = dropped.get(reason, 0) + 1
                continue
            if item["id"] in held:
                _refresh_incident(held[item["id"]], item)
                continue
            if item["id"] in seen:
                continue
            if added >= news_cfg.max_new_items_per_source:
                # Not marked as seen: it is picked up by a later run instead.
                dropped["over per-source limit"] = dropped.get("over per-source limit", 0) + 1
                continue
            seen[item["id"]] = timestamp
            new_items.append(item)
            added += 1
        log.info("  %-28s %d entries, %d new", source["id"], len(result.entries), added)

    new_items = news.merge_items([], new_items)

    # Items still carrying only a keyword score — new ones, and any a previous
    # run could not enrich because the model was down — are queued with the
    # most promising first, so a capped run spends its calls where they matter.
    usage: Dict[str, Any] = {"calls": 0, "prompt_tokens": 0, "output_tokens": 0, "errors": []}
    story_links: Dict[str, str] = {}
    if enrich and news_cfg.enrich and not dry_run:
        pending = [i for i in new_items + existing if i.get("relevance_source") != "model"]
        queue = sorted(pending, key=lambda i: (i["relevance"], i["published"]), reverse=True)
        queue = queue[: news_cfg.max_enrich_items]
        if queue:
            queued = {i["id"] for i in queue}
            earlier = sorted(
                (i for i in existing if i["id"] not in queued and i["published"] >= _days_ago(now, STORY_DAYS)),
                key=lambda i: (i.get("relevance", 0), i["published"]),
                reverse=True,
            )
            outcome = news_enrichment.enrich(
                queue,
                model=cfg.model,
                batch_size=news_cfg.enrich_batch_size,
                vendors=_vendors(policy_sets),
                earlier=earlier[: news_enrichment.MAX_CONTEXT],
            )
            results = outcome.results
            new_items = [news_enrichment.apply(i, results[i["id"]]) if i["id"] in results else i for i in new_items]
            existing = [news_enrichment.apply(i, results[i["id"]]) if i["id"] in results else i for i in existing]
            story_links = {k: r["same_story_as"] for k, r in results.items() if r.get("same_story_as")}
            usage = {
                "calls": outcome.calls,
                "prompt_tokens": outcome.prompt_tokens,
                "output_tokens": outcome.output_tokens,
                "errors": outcome.errors[:5],
                "enriched": len(results),
            }
            if outcome.calls == 0 and outcome.errors:
                log.warning("  Enrichment skipped (%s) — items keep their keyword scores", outcome.errors[0])
            else:
                log.info(
                    "  Enriched %d of %d queued item(s) in %d call(s)%s",
                    len(results),
                    len(queue),
                    outcome.calls,
                    f" — {len(outcome.errors)} batch error(s)" if outcome.errors else "",
                )
    elif new_items and enrich and news_cfg.enrich:
        log.info("  [dry-run] Would enrich up to %d item(s)", min(len(new_items), news_cfg.max_enrich_items))

    kept = [item for item in new_items if item["relevance"] >= news_cfg.min_relevance]
    below = len(new_items) - len(kept)
    if below:
        dropped["below minimum relevance"] = dropped.get("below minimum relevance", 0) + below
    # A held item the model has now judged irrelevant leaves the feed too.
    existing = [i for i in existing if i.get("relevance", 0) >= news_cfg.min_relevance]

    merged = news.merge_items(existing, kept)
    before_fold = len(merged)
    merged = news.fold_same_story(merged, story_links)
    if before_fold != len(merged):
        log.info("  Folded %d repeat report(s) into the stories they cover", before_fold - len(merged))
    current, aged = news.split_window(merged, now=now, window_days=news_cfg.window_days)
    archived = append_to_archive(aged, dry_run)

    known_ids = {s["id"] for s in all_sources}
    counts: Dict[str, int] = {}
    for item in current:
        counts[item["source_id"]] = counts.get(item["source_id"], 0) + 1

    threshold = cfg.health.consecutive_failure_threshold
    sources_block = {}
    for source in all_sources:
        record = source_state.get(source["id"], {})
        sources_block[source["id"]] = {
            "name": source["name"],
            "category": source["category"],
            "kind": source.get("kind", news.KIND_NEWS),
            "homepage": source.get("homepage", ""),
            "via": source.get("via", ""),
            "note": source.get("note", ""),
            "status": _source_status(int(record.get("consecutive_failures", 0)), threshold)
            if record else "unknown",
            "last_checked": record.get("last_checked"),
            "last_success": record.get("last_success"),
            "consecutive_failures": int(record.get("consecutive_failures", 0)),
            "last_error": record.get("last_error", ""),
            "items": counts.get(source["id"], 0),
        }

    output = {
        "generated_at": timestamp,
        "window_days": news_cfg.window_days,
        "min_relevance": news_cfg.min_relevance,
        "sources": sources_block,
        "items": current,
    }
    run_summary = {
        "timestamp": timestamp,
        "sources_checked": len(sources),
        "sources_ok": fetched_ok,
        "new_items": len(kept),
        "archived": archived,
        "dropped": dropped,
        "model": usage,
    }

    log.info(
        "News run complete — %d/%d source(s) read, %d new item(s) kept, %d in window, dropped: %s",
        fetched_ok,
        len(sources),
        len(kept),
        len(current),
        dropped or "none",
    )

    if dry_run:
        for item in kept[:15]:
            log.info("  [%d] %s — %s", item["relevance"], item["source_id"], item["title"][:90])
        log.info("Nothing was written to disk.")
        return 0 if fetched_ok else 1

    save_json(output, FEED_FILE)
    save_json(
        {
            "sources": {k: v for k, v in source_state.items() if k in known_ids},
            "seen": news.prune_seen(seen, now=now, keep_days=news_cfg.window_days + SEEN_GRACE_DAYS),
            "last_run": run_summary,
        },
        STATE_FILE,
    )
    return 0 if fetched_ok else 1


def _refresh_incident(held: dict, fresh: dict) -> None:
    """Keep an incident's article count current as the story is reported."""
    if held.get("incident") and fresh.get("incident"):
        held["incident"]["articles"] = max(
            int(held["incident"].get("articles", 0)), int(fresh["incident"].get("articles", 0))
        )


# --- Entry point ----------------------------------------------------------------------


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Refresh the news and AI-incident feed.")
    parser.add_argument("--dry-run", action="store_true", help="Fetch and gate, but write nothing.")
    parser.add_argument("--config", default="steward_config.yaml", help="Path to the config file.")
    parser.add_argument(
        "--only", action="append", default=None, metavar="SOURCE_ID",
        help="Limit the run to one source id from news_sources.json. Repeatable.",
    )
    parser.add_argument(
        "--no-enrich", action="store_true",
        help="Skip the model; items keep their keyword score and publisher excerpt.",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    args = parse_args(argv)
    try:
        cfg = load_config(args.config)
    except ConfigError as exc:
        log.error("Configuration error — %s", exc)
        return 1
    if not args.no_enrich and not args.dry_run and not os.environ.get("GEMINI_API_KEY"):
        log.warning("GEMINI_API_KEY is not set — items will keep their keyword scores")
    return run(cfg, dry_run=args.dry_run, only=args.only, enrich=not args.no_enrich)


if __name__ == "__main__":
    sys.exit(main())
