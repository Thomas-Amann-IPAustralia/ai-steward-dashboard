"""Turning feed entries into dashboard items — the news feed's filtration.

The policy pipeline's rule carries over: cheap deterministic gates first, one
model call last, and the model is never the only thing standing between the
reader and noise.

1. **Window.** Anything published before the retention window is ignored
   rather than ingested and immediately archived — OpenAI's feed alone
   carries twelve hundred items going back years.
2. **Identity.** An item's id is a hash of its canonical URL (tracking
   parameters, fragments and `www.` removed), so the same story arriving
   from two feeds, or twice from one, is one item.
3. **AI gate.** General feeds (a PM's media releases, the Mandarin, SBS) are
   only admitted when the *headline* is about AI. An excerpt-only mention is
   a press-conference transcript that touched on AI in passing — noise for
   the reader and tokens for the model. Sources that are about AI by
   construction are marked `ai_focused` and skip the gate. Live blogs,
   podcasts and cartoons are dropped by title (`news.exclude_title_patterns`):
   the same news arrives as a proper article.
4. **Keyword relevance.** A 0–3 score with its reasons, built from the same
   Australian-government and policy vocabulary the model is given. It is the
   fallback when the model is unavailable, and the order in which items are
   sent to it.
5. **Cross-links.** An item naming a vendor or agency whose policies are
   monitored is linked to that policy set — a dictionary lookup, no vectors.
6. **One story, one item.** Near-identical headlines are folded together
   here, before the model is called, so it never pays to read a story twice;
   the direct publisher's copy (with its excerpt) is preferred over a Google
   News copy of the same headline. The model folds the rest (fifteen
   outlets' takes on one event). The other outlets are kept as `coverage` on
   the lead item, which is itself a signal of how big the story is.

Newsletter and article text is third-party copyright going onto a public
site, so an item stores a headline, a link, a short publisher excerpt and our
own summary — never the article body, and never remote images.
"""

from __future__ import annotations

import hashlib
import html
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from bs4 import BeautifulSoup

from .feeds import FeedEntry

KIND_NEWS = "news"
KIND_INCIDENT = "incident"
KINDS = (KIND_NEWS, KIND_INCIDENT)

TOPICS = (
    "government_policy",
    "regulation",
    "privacy",
    "security",
    "safety",
    "vendors",
    "public_sector",
    "workforce",
    "research",
)

EXCERPT_CHARS = 320
# Google News item links redirect through here rather than to the outlet.
AGGREGATOR_HOST = "news.google.com"
# Most other outlets listed against one story.
MAX_COVERAGE = 20

_TRACKING_PARAMS = re.compile(
    r"^(utm_[a-z]+|fbclid|gclid|dclid|mc_cid|mc_eid|ocid|cmpid|oc|ref|ref_src|"
    r"_hsenc|_hsmi|mkt_tok|igshid|spm|sr_share)$",
    re.IGNORECASE,
)
_WHITESPACE = re.compile(r"\s+")
# Publisher furniture at the end of an excerpt: WordPress's "The post …
# appeared first on …", and the Guardian's newsletter, app and live-blog
# plugs. Stripped repeatedly from the end, so they cost neither the reader's
# attention nor the model's tokens.
_TRAILING_FURNITURE = (
    re.compile(r"\s*The post .{1,300}? appeared first on .{1,120}?\.?\s*$", re.IGNORECASE),
    re.compile(r"\s*Continue reading(?:\.\.\.|…)?\s*$", re.IGNORECASE),
    re.compile(r"\s*Get our [\w\s-]{1,40}email\s*,\s*free app or daily news podcast\.?\s*$", re.IGNORECASE),
    re.compile(r"\s*Follow (?:our [\w\s]{1,30}live blog for (?:the )?latest updates|the day[’']s news live)\.?\s*$", re.IGNORECASE),
)


# --- URLs and identity ----------------------------------------------------------


def canonical_url(url: str) -> Optional[str]:
    """The URL with tracking noise removed, or None if it is not http(s)."""
    try:
        parsed = urlparse((url or "").strip())
    except ValueError:
        return None
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        return None

    query = [(k, v) for k, v in parse_qsl(parsed.query, keep_blank_values=True) if not _TRACKING_PARAMS.match(k)]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc.lower(),
            parsed.path or "/",
            parsed.params,
            urlencode(query, doseq=True),
            "",
        )
    )


def item_id(url: str) -> str:
    """Stable id for an item, from its canonical URL without scheme or www."""
    key = re.sub(r"^https?://(www\.)?", "", url or "", flags=re.IGNORECASE).rstrip("/").lower()
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:16]


# --- Text -----------------------------------------------------------------------


def clean_text(fragment: str) -> str:
    """Plain text from an HTML or text fragment, whitespace collapsed."""
    if not fragment:
        return ""
    if "<" in fragment and ">" in fragment:
        # Images are dropped with the markup: newsletter and blog excerpts are
        # full of tracking pixels, and nothing remote is ever rendered.
        fragment = BeautifulSoup(fragment, "html.parser").get_text(" ")
    text = _WHITESPACE.sub(" ", html.unescape(fragment)).strip()
    stripped = None
    while stripped != text:
        stripped = text
        for pattern in _TRAILING_FURNITURE:
            text = pattern.sub("", text)
    return text.strip()


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    """At most `limit` characters, cut at a word boundary."""
    if len(text) <= limit:
        return text
    cut = text[:limit].rsplit(" ", 1)[0].rstrip(" ,;:-")
    return f"{cut}…"


def split_publisher(title: str, publisher: str) -> str:
    """Google News appends ' - Publisher' to every headline; drop it."""
    if publisher and title.endswith(f" - {publisher}"):
        return title[: -len(f" - {publisher}")].strip()
    return title


def _similar(a: str, b: str) -> bool:
    words_a = set(re.findall(r"\w+", a.lower()))
    words_b = set(re.findall(r"\w+", b.lower()))
    if not words_a or not words_b:
        return False
    return len(words_a & words_b) / len(words_a | words_b) >= 0.8


# --- Matching ------------------------------------------------------------------


def compile_terms(terms: Sequence[str]) -> Optional[re.Pattern]:
    """One regex over a term list, whole words only.

    An all-caps term (AI, DTA, ISM) is matched case-sensitively, so 'AI' is
    not found in 'said' and 'ISM' not in 'tourism'; anything else is matched
    without regard to case.
    """
    sensitive = [re.escape(t) for t in terms if t.isupper()]
    insensitive = [re.escape(t) for t in terms if t and not t.isupper()]
    # Lookarounds rather than \b, so a term ending in punctuation ("A.I.")
    # still has a boundary to match against.
    parts = []
    if sensitive:
        parts.append(rf"(?<!\w)(?:{'|'.join(sensitive)})(?!\w)")
    if insensitive:
        parts.append(rf"(?i:(?<!\w)(?:{'|'.join(insensitive)})(?!\w))")
    return re.compile("|".join(parts)) if parts else None


def matches(pattern: Optional[re.Pattern], text: str) -> List[str]:
    if pattern is None or not text:
        return []
    seen: Dict[str, None] = {}
    for hit in pattern.finditer(text):
        seen.setdefault(hit.group(0).lower(), None)
    return list(seen)


@dataclass
class Vocabulary:
    """The compiled term lists the gates and the scorer share."""

    ai: Optional[re.Pattern]
    australia: Optional[re.Pattern]
    government: Optional[re.Pattern]
    policy: Optional[re.Pattern]
    risk: Optional[re.Pattern]
    excluded_titles: Tuple[re.Pattern, ...] = ()

    @classmethod
    def from_config(cls, news_cfg) -> "Vocabulary":
        return cls(
            ai=compile_terms(news_cfg.ai_terms),
            australia=compile_terms(news_cfg.australia_terms),
            government=compile_terms(news_cfg.government_terms),
            policy=compile_terms(news_cfg.policy_terms),
            risk=compile_terms(news_cfg.risk_terms),
            excluded_titles=tuple(re.compile(p) for p in news_cfg.exclude_title_patterns),
        )


@dataclass
class PolicyLink:
    file_id: str
    set_name: str
    pattern: re.Pattern


def policy_links(policy_sets: Iterable[dict], file_id_for) -> List[PolicyLink]:
    """Cross-link patterns from each policy set's optional `keywords`."""
    links = []
    for policy_set in policy_sets:
        keywords = [k for k in policy_set.get("keywords") or [] if isinstance(k, str) and k.strip()]
        pattern = compile_terms(keywords)
        if pattern is not None:
            name = policy_set["setName"]
            links.append(PolicyLink(file_id_for(name), name, pattern))
    return links


def related_policies(text: str, links: Sequence[PolicyLink]) -> List[str]:
    return [link.file_id for link in links if link.pattern.search(text)]


# --- Relevance ------------------------------------------------------------------


def keyword_relevance(
    text: str,
    vocab: Vocabulary,
    *,
    kind: str,
    related: Sequence[str],
    country_code: str = "",
    ai_focused: bool = False,
) -> Tuple[int, str]:
    """A 0–3 score and a one-line reason, from vocabulary alone.

    The same four bands the model is given: 3 highly relevant, 2 directly relevant
    context, 1 worth knowing, 0 skip.
    """
    ai = ai_focused or kind == KIND_INCIDENT or bool(matches(vocab.ai, text))
    if not ai:
        return 0, "Not about AI"

    australian = country_code == "AUS" or bool(matches(vocab.australia, text))
    government = bool(matches(vocab.government, text))
    policy = bool(matches(vocab.policy, text))
    risk = bool(matches(vocab.risk, text))

    if australian and (government or policy):
        return 3, "Australian government or policy development on AI"
    if kind == KIND_INCIDENT and australian:
        return 3, "AI incident in Australia"
    if australian:
        return 2, "AI development in Australia"
    if related:
        return 2, "Involves a provider whose policies are monitored here"
    if policy and government:
        return 2, "AI regulation or government policy elsewhere"
    if kind == KIND_INCIDENT and government:
        return 2, "AI incident involving government"
    if risk or policy:
        return 1, "AI risk, safety or governance development"
    return 1, "General AI news"


# --- Items ------------------------------------------------------------------------


def build_item(
    entry: FeedEntry,
    source: dict,
    *,
    now: datetime,
    window_days: int,
    vocab: Vocabulary,
    links: Sequence[PolicyLink],
) -> Tuple[Optional[Dict[str, Any]], str]:
    """An item from a feed entry, or (None, reason it was dropped)."""
    url = canonical_url(entry.link)
    if url is None:
        return None, "no usable link"

    published = entry.published or now
    if published > now + timedelta(days=1):
        # A feed dated in the future is wrong about the date, not early.
        published = now
    if published < now - timedelta(days=window_days):
        return None, "outside window"

    title = clean_text(split_publisher(entry.title, entry.publisher))
    if not title:
        return None, "no title"
    if any(pattern.search(title) for pattern in vocab.excluded_titles):
        return None, "live blog, podcast or similar"

    summary = clean_text(entry.summary)
    # Aggregator excerpts are often just the headline again, or a list of
    # links to the same story elsewhere.
    if summary and (summary.startswith(title[:60]) or _similar(summary[: len(title) + 40], title)):
        summary = ""
    summary = excerpt(summary)

    kind = KIND_INCIDENT if entry.incident else source.get("kind", KIND_NEWS)
    text = f"{title}\n{summary}"
    ai_focused = bool(source.get("ai_focused")) or kind == KIND_INCIDENT
    if not ai_focused and not matches(vocab.ai, title):
        return None, "not about AI"

    related = related_policies(text, links)
    incident = dict(entry.incident) if entry.incident else None
    relevance, reason = keyword_relevance(
        text,
        vocab,
        kind=kind,
        related=related,
        country_code=(incident or {}).get("country_code", ""),
        ai_focused=ai_focused,
    )
    # A source can vouch for its own items (the UK AI Security Institute
    # publishes nothing that is merely "general AI news"), but never lift an
    # item that is not about AI at all.
    floor = int(source.get("relevance_floor", 0))
    relevance = max(relevance, floor) if relevance > 0 else relevance

    item: Dict[str, Any] = {
        "id": item_id(url),
        "kind": kind,
        "title": title,
        "url": url,
        "source_id": source["id"],
        "source_name": source["name"],
        "category": source.get("category", ""),
        # The outlet as a reader knows it: named by the aggregator for a
        # Google News item, by the source entry for a direct feed.
        "publisher": entry.publisher or source.get("publisher", ""),
        "published": published.astimezone(timezone.utc).isoformat(),
        "first_seen": now.astimezone(timezone.utc).isoformat(),
        "summary": summary,
        "tldr": "",
        "relevance": relevance,
        "relevance_reason": reason,
        "relevance_source": "keywords",
        "topics": [],
        "related_policies": related,
    }
    if source.get("paywalled"):
        item["paywalled"] = True
    if incident:
        item["incident"] = incident
    return item, ""


def coverage_entry(item: dict) -> dict:
    return {
        "title": item.get("title", ""),
        "url": item.get("url", ""),
        "publisher": item.get("publisher") or item.get("source_name", ""),
        "published": item.get("published", ""),
    }


def add_coverage(lead: dict, other: dict) -> None:
    """Record `other` (and anything already folded into it) against `lead`."""
    coverage = lead.setdefault("coverage", [])
    known = {entry["url"] for entry in coverage} | {lead.get("url")}
    for entry in [coverage_entry(other)] + list(other.get("coverage", [])):
        if entry["url"] not in known and len(coverage) < MAX_COVERAGE:
            coverage.append(entry)
            known.add(entry["url"])
    lead["relevance"] = max(int(lead.get("relevance", 0)), int(other.get("relevance", 0)))
    for file_id in other.get("related_policies", []):
        if file_id not in lead.setdefault("related_policies", []):
            lead["related_policies"].append(file_id)


def is_aggregated(item: dict) -> bool:
    """Whether an item's link goes through an aggregator rather than to the outlet."""
    return (urlparse(item.get("url", "")).hostname or "") == AGGREGATOR_HOST


def _richness(item: dict) -> int:
    """How much a copy of a story gives the reader: a direct link, then an excerpt."""
    return (0 if is_aggregated(item) else 2) + (1 if item.get("summary") else 0)


def merge_items(existing: Sequence[dict], incoming: Sequence[dict]) -> List[dict]:
    """Existing items plus new ones, one per id and one per near-identical headline.

    When an arrival repeats a story already held, one copy leads and the other
    is recorded as its coverage rather than listed twice. The held copy leads,
    unless the newcomer is the outlet's own (a direct link and an excerpt
    rather than a Google News redirect) and the held copy has not yet been
    through the model — an enriched item is never displaced.
    """
    merged: Dict[str, dict] = {item["id"]: item for item in existing if item.get("id")}
    for item in incoming:
        if item["id"] in merged:
            continue
        duplicate = next(
            (
                held
                for held in merged.values()
                if held.get("kind") == item.get("kind") and _similar(held.get("title", ""), item["title"])
            ),
            None,
        )
        if duplicate is None:
            merged[item["id"]] = item
        elif _richness(item) > _richness(duplicate) and duplicate.get("relevance_source") != "model":
            del merged[duplicate["id"]]
            add_coverage(item, duplicate)
            merged[item["id"]] = item
        else:
            add_coverage(duplicate, item)
    return sorted(merged.values(), key=lambda i: i.get("published", ""), reverse=True)


def fold_same_story(items: Sequence[dict], links: Dict[str, str]) -> List[dict]:
    """Fold each item into the story it was judged to repeat.

    `links` maps an item id to the id of the item reporting the same event.
    Chains are followed to their end; a cycle, a missing target or a link
    across kinds (a news report onto an incident record) leaves the item as
    its own story.
    """
    by_id = {item["id"]: item for item in items}

    def lead_of(item_id: str) -> str:
        visited = set()
        current = item_id
        while current in links and links[current] in by_id and current not in visited:
            visited.add(current)
            current = links[current]
        return item_id if current in visited else current

    folded = set()
    for item in items:
        lead_id = lead_of(item["id"])
        if lead_id == item["id"] or lead_id in folded:
            continue
        lead = by_id[lead_id]
        if lead.get("kind") != item.get("kind"):
            continue
        add_coverage(lead, item)
        folded.add(item["id"])
    return [item for item in items if item["id"] not in folded]


def split_window(items: Sequence[dict], *, now: datetime, window_days: int) -> Tuple[List[dict], List[dict]]:
    """(items inside the window, items that have aged out)."""
    cutoff = (now - timedelta(days=window_days)).astimezone(timezone.utc).isoformat()
    current = [item for item in items if item.get("published", "") >= cutoff]
    aged = [item for item in items if item.get("published", "") < cutoff]
    return current, aged


def archive_month(item: dict) -> str:
    return (item.get("published") or "")[:7] or "undated"


def prune_seen(seen: Dict[str, str], *, now: datetime, keep_days: int) -> Dict[str, str]:
    """Drop remembered ids old enough that their items can no longer reappear."""
    cutoff = (now - timedelta(days=keep_days)).astimezone(timezone.utc).isoformat()
    return {key: when for key, when in seen.items() if when >= cutoff}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
