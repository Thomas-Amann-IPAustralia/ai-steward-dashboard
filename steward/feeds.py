"""Fetching and parsing the news and incident sources.

Two source types, both reduced to the same `FeedEntry` shape:

* ``rss`` — RSS 2.0, RSS 1.0 (RDF) and Atom, parsed with the standard
  library. feedparser was the obvious choice but depends on an sdist-only
  package that does not always build, and a feed reader that breaks the
  daily run is worse than one that handles the three formats that matter.
  A conditional GET is sent with the stored ETag / Last-Modified, exactly as
  the policy pipeline does, so an unchanged feed costs one header exchange.
* ``oecd_aim`` — the OECD AI Incidents Monitor's own search API, the same
  endpoint oecd.ai's incident browser posts to. It returns structured
  incidents (country, harm level, industries, article counts) rather than
  headlines, which is what makes "incidents in Australia" answerable at all.

Nothing here writes files or decides relevance: it turns bytes into entries.
"""

from __future__ import annotations

import email.utils
import logging
import re
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests

from .fetching import is_safe_url

log = logging.getLogger(__name__)

OK = "ok"
NOT_MODIFIED = "not_modified"
FAILED = "failed"

TYPE_RSS = "rss"
TYPE_OECD_AIM = "oecd_aim"
SOURCE_TYPES = (TYPE_RSS, TYPE_OECD_AIM)

OECD_AIM_ENDPOINT = "https://incidents-server.oecdai.org/api/v1/incidents/fetch-incidents"
OECD_AIM_INCIDENT_URL = "https://oecd.ai/en/incidents/{id}"
# The API refuses more than this per request.
OECD_AIM_MAX_RESULTS = 100

# A feed larger than this is not a feed.
MAX_FEED_BYTES = 8 * 1024 * 1024


@dataclass
class FeedEntry:
    title: str
    link: str
    guid: str = ""
    published: Optional[datetime] = None
    summary: str = ""
    # The outlet behind an aggregator item (Google News names it separately).
    publisher: str = ""
    incident: Optional[Dict[str, Any]] = None


@dataclass
class FeedResult:
    source_id: str
    status: str
    entries: List[FeedEntry] = field(default_factory=list)
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    http_status: Optional[int] = None
    error: str = ""
    duration_ms: int = 0

    @property
    def ok(self) -> bool:
        return self.status in (OK, NOT_MODIFIED)


# --- Dates -------------------------------------------------------------------

# Formats seen in the wild that neither RFC 822 nor ISO 8601 parsing accepts,
# e.g. pm.gov.au's "Thursday 24 September 2026".
_LOOSE_FORMATS = (
    "%A %d %B %Y",
    "%A, %d %B %Y",
    "%d %B %Y",
    "%B %d, %Y",
    "%Y-%m-%d",
    "%a, %d %b %Y %H:%M:%S",
)


def parse_date(value: Optional[str]) -> Optional[datetime]:
    """Best-effort timezone-aware datetime from a feed date string."""
    if not value:
        return None
    value = value.strip()

    try:
        parsed = email.utils.parsedate_to_datetime(value)
        if parsed is not None:
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError, IndexError):
        pass

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        pass

    for fmt in _LOOSE_FORMATS:
        try:
            return datetime.strptime(value, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


# --- XML feeds -----------------------------------------------------------------


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _child(element: ET.Element, *names: str) -> Optional[ET.Element]:
    """First child matching the earliest-listed name, in order of preference."""
    children = list(element)
    for name in names:
        for child in children:
            if _local(child.tag) == name:
                return child
    return None


def _text(element: Optional[ET.Element]) -> str:
    if element is None:
        return ""
    # Atom text constructs may carry markup as child elements.
    return "".join(element.itertext()).strip()


def _atom_link(entry: ET.Element) -> str:
    fallback = ""
    for child in entry:
        if _local(child.tag) != "link":
            continue
        href = (child.attrib.get("href") or "").strip()
        rel = child.attrib.get("rel", "alternate")
        if href and rel == "alternate":
            return href
        fallback = fallback or href
    return fallback


class FeedParseError(ValueError):
    """The body was not a feed we can read."""


def parse_feed(body: bytes) -> List[FeedEntry]:
    """Entries from an RSS 2.0, RSS 1.0 or Atom document."""
    head = body[:4096].lower()
    # Entity declarations are how XML bombs and external-entity reads start,
    # and no news feed needs one.
    if b"<!entity" in head:
        raise FeedParseError("document declares entities; refused")

    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        raise FeedParseError(f"not well-formed XML ({exc})") from exc

    kind = _local(root.tag)
    if kind not in ("rss", "RDF", "feed"):
        raise FeedParseError(f"unexpected root element <{kind}>")

    entries: List[FeedEntry] = []
    for element in root.iter():
        name = _local(element.tag)
        if name == "item":
            link = _text(_child(element, "link"))
            guid = _text(_child(element, "guid"))
            if not link and guid.startswith("http"):
                link = guid
            source = _child(element, "source")
            entries.append(
                FeedEntry(
                    title=_text(_child(element, "title")),
                    link=link,
                    guid=guid or element.attrib.get(
                        "{http://www.w3.org/1999/02/22-rdf-syntax-ns#}about", ""
                    ),
                    published=parse_date(_text(_child(element, "pubDate", "date", "published", "updated"))),
                    summary=_text(_child(element, "description", "summary", "encoded")),
                    publisher=_text(source),
                )
            )
        elif name == "entry":
            entries.append(
                FeedEntry(
                    title=_text(_child(element, "title")),
                    link=_atom_link(element),
                    guid=_text(_child(element, "id")),
                    published=parse_date(_text(_child(element, "published", "updated"))),
                    summary=_text(_child(element, "summary", "content")),
                )
            )
    return [entry for entry in entries if entry.title and entry.link]


def _conditional_headers(state: dict, user_agent: str) -> dict:
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5",
        "Accept-Language": "en-AU,en;q=0.9",
    }
    if state.get("etag"):
        headers["If-None-Match"] = state["etag"]
    if state.get("last_modified"):
        headers["If-Modified-Since"] = state["last_modified"]
    return headers


def fetch_rss(source: dict, state: dict, *, timeout: int, user_agent: str) -> FeedResult:
    url = source["url"]
    started = time.monotonic()

    def done(result: FeedResult) -> FeedResult:
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    if not is_safe_url(url):
        return done(FeedResult(source["id"], FAILED, error="unsafe or malformed URL, refused"))

    try:
        response = requests.get(url, headers=_conditional_headers(state, user_agent), timeout=timeout)
    except requests.RequestException as exc:
        return done(FeedResult(source["id"], FAILED, error=f"{type(exc).__name__}: {exc}"))

    if response.status_code == 304:
        return done(
            FeedResult(
                source["id"],
                NOT_MODIFIED,
                etag=state.get("etag"),
                last_modified=state.get("last_modified"),
                http_status=304,
            )
        )
    if response.status_code >= 400:
        return done(
            FeedResult(
                source["id"], FAILED, http_status=response.status_code, error=f"HTTP {response.status_code}"
            )
        )
    if len(response.content) > MAX_FEED_BYTES:
        return done(FeedResult(source["id"], FAILED, http_status=response.status_code, error="feed too large"))

    try:
        entries = parse_feed(response.content)
    except FeedParseError as exc:
        return done(FeedResult(source["id"], FAILED, http_status=response.status_code, error=str(exc)))

    return done(
        FeedResult(
            source["id"],
            OK,
            entries=entries,
            etag=response.headers.get("ETag"),
            last_modified=response.headers.get("Last-Modified"),
            http_status=response.status_code,
        )
    )


# --- OECD AI Incidents Monitor ----------------------------------------------------


def aim_request_body(query: dict, today: datetime) -> dict:
    """The search the oecd.ai incident browser would send for this query."""
    lookback = int(query.get("lookback_days", 30))
    return {
        "search_terms": [],
        "and_condition": False,
        "from_date": (today - timedelta(days=lookback)).strftime("%Y-%m-%d"),
        "to_date": today.strftime("%Y-%m-%d"),
        "countries": list(query.get("countries", [])),
        "properties_config": {
            "principles": [],
            "industries": list(query.get("industries", [])),
            "harm_types": [],
            "harm_levels": [],
            "harmed_entities": list(query.get("harmed_entities", [])),
            "business_functions": [],
            "ai_tasks": [],
            "autonomy_levels": [],
            "languages": [],
        },
        "order_by": query.get("order_by", "date"),
        "num_results": min(int(query.get("num_results", 50)), OECD_AIM_MAX_RESULTS),
        "format": "JSON",
    }


def _as_list(value: Any) -> List[str]:
    return [str(v) for v in value] if isinstance(value, list) else []


def aim_entry(incident: dict) -> Optional[FeedEntry]:
    """One OECD AIM incident as a feed entry, or None if it is unusable."""
    incident_id = str(incident.get("id") or "").strip()
    title = str(incident.get("title") or "").strip()
    if not incident_id or not title or not re.fullmatch(r"[\w-]+", incident_id):
        return None

    properties = incident.get("properties") if isinstance(incident.get("properties"), dict) else {}
    location = incident.get("location") if isinstance(incident.get("location"), dict) else {}
    harm_levels = _as_list(properties.get("harm_levels"))

    return FeedEntry(
        title=title,
        link=OECD_AIM_INCIDENT_URL.format(id=incident_id),
        guid=f"oecd-aim:{incident_id}",
        published=parse_date(incident.get("date")),
        summary=str(incident.get("summary") or "").strip(),
        publisher="OECD AI Incidents Monitor",
        incident={
            "source": "oecd_aim",
            "incident_id": incident_id,
            "country": location.get("country") or "",
            "country_code": location.get("country_code") or "",
            "harm_level": harm_levels[0] if harm_levels else "",
            "harm_types": _as_list(properties.get("harm_types")),
            "harmed_entities": _as_list(properties.get("harmed_entities")),
            "industries": _as_list(properties.get("industries")),
            "principles": _as_list(properties.get("principles")),
            "autonomy_level": properties.get("autonomy_level") or "",
            "articles": int(incident.get("n_articles") or 0),
            "aiid_ids": [int(i) for i in incident.get("aiid_ids") or [] if str(i).isdigit()],
        },
    )


def fetch_oecd_aim(source: dict, *, timeout: int, user_agent: str, today: Optional[datetime] = None) -> FeedResult:
    started = time.monotonic()
    query = source.get("query") or {}
    body = aim_request_body(query, today or datetime.now(timezone.utc))

    def done(result: FeedResult) -> FeedResult:
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    try:
        response = requests.post(
            OECD_AIM_ENDPOINT,
            json=body,
            headers={"User-Agent": user_agent, "Accept": "application/json"},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        return done(FeedResult(source["id"], FAILED, error=f"{type(exc).__name__}: {exc}"))

    if response.status_code >= 400:
        return done(
            FeedResult(source["id"], FAILED, http_status=response.status_code, error=f"HTTP {response.status_code}")
        )

    try:
        payload = response.json()
    except ValueError:
        return done(FeedResult(source["id"], FAILED, http_status=response.status_code, error="response was not JSON"))

    incidents = payload.get("incidents") if isinstance(payload, dict) else None
    if not isinstance(incidents, list):
        return done(
            FeedResult(source["id"], FAILED, http_status=response.status_code, error="no incidents list in response")
        )

    min_articles = int(query.get("min_articles", 0))
    entries = []
    for incident in incidents:
        if not isinstance(incident, dict) or int(incident.get("n_articles") or 0) < min_articles:
            continue
        entry = aim_entry(incident)
        if entry is not None:
            entries.append(entry)

    return done(FeedResult(source["id"], OK, entries=entries, http_status=response.status_code))


def fetch_source(source: dict, state: dict, *, timeout: int, user_agent: str) -> FeedResult:
    if source["type"] == TYPE_OECD_AIM:
        return fetch_oecd_aim(source, timeout=timeout, user_agent=user_agent)
    return fetch_rss(source, state, timeout=timeout, user_agent=user_agent)
