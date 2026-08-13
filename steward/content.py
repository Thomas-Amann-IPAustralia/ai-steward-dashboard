"""Normalisation and hashing — the gate that kills cosmetic noise.

Hashing raw extracted text makes every whitespace wobble, entity change and
rotating banner look like a policy amendment. Normalising first is what stops
runs like 7 August 2026, where a paid model call came back with "there are no
changes between the provided old and new policy documents".

`normalise` is idempotent: normalise(normalise(t)) == normalise(t). Stored
snapshots are already normalised, so re-normalising them on read must be a
no-op or every comparison drifts.
"""

from __future__ import annotations

import hashlib
import html
import re
import unicodedata
from typing import Iterable, Sequence
from urllib.parse import urlparse

# Horizontal whitespace only — newlines are structure and survive this pass.
_HORIZONTAL_WS = re.compile(r"[^\S\n]+")
_BLANK_RUNS = re.compile(r"\n{3,}")
# Zero-width space, ZWNJ, ZWJ, word joiner, BOM.
_ZERO_WIDTH = dict.fromkeys(map(ord, "​‌‍⁠﻿"))
_NBSP = " "

# Folded so a curly apostrophe cannot hide a block page from the failure
# signatures. Chrome renders "This site can’t be reached" with U+2019, which
# is precisely how the 8 August 2026 capture passed the check.
_QUOTE_FOLD = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "‚": "'",
        "‛": "'",
        "′": "'",
        "“": '"',
        "”": '"',
        "„": '"',
        "″": '"',
        "–": "-",
        "—": "-",
        "−": "-",
        " ": " ",
    }
)

_MAX_UNESCAPE_PASSES = 5


def host_of(url: str) -> str:
    """Hostname of a URL, or '' if it has none."""
    try:
        return urlparse(url).hostname or ""
    except ValueError:
        return ""


def fold_for_matching(text: str) -> str:
    """Case- and quote-folded copy, for substring matching only.

    Never store the result: it is lossy by design.
    """
    return text.translate(_QUOTE_FOLD).casefold()


def _unescape_to_fixed_point(text: str) -> str:
    """Decode HTML entities until decoding stops changing the text.

    A single pass is not idempotent — '&amp;lt;' decodes to '&lt;' and then to
    '<' — which would make normalise() unstable across runs.
    """
    for _ in range(_MAX_UNESCAPE_PASSES):
        decoded = html.unescape(text)
        if decoded == text:
            return text
        text = decoded
    return text


def normalise(text: str | None, noise_patterns: Sequence[str] = ()) -> str:
    """Collapse cosmetic variation so only real edits survive to the hash."""
    if not text:
        return ""

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = _unescape_to_fixed_point(text)
    text = unicodedata.normalize("NFC", text)
    text = text.translate(_ZERO_WIDTH)
    text = text.replace(_NBSP, " ")

    for pattern in noise_patterns:
        text = re.sub(pattern, "", text, flags=re.MULTILINE)

    lines = [_HORIZONTAL_WS.sub(" ", line).strip() for line in text.split("\n")]
    text = "\n".join(lines)
    text = _BLANK_RUNS.sub("\n\n", text)
    return text.strip()


def content_hash(text: str) -> str:
    """Stable hash of already-normalised text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def document_id(url: str) -> str:
    """Short, filesystem-safe, stable id for a URL within a policy set."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", urlparse(url).path or "").strip("-")
    slug = slug[-48:].strip("-").lower() or "root"
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:8]
    return f"{slug}-{digest}"


def document_label(url_data: dict) -> str:
    """Human-readable name for a document, for 'which one changed' displays."""
    explicit = (url_data.get("label") or "").strip()
    if explicit:
        return explicit

    path = urlparse(url_data.get("url", "")).path.rstrip("/")
    tail = path.rsplit("/", 1)[-1] if path else ""
    if not tail:
        return host_of(url_data.get("url", "")) or url_data.get("url", "")

    tail = re.sub(r"\.(html?|php|aspx?)$", "", tail, flags=re.IGNORECASE)
    tail = re.sub(r"^\d+[-_]", "", tail)
    words = [w for w in re.split(r"[-_]+", tail) if w]
    if not words:
        return host_of(url_data.get("url", ""))
    return " ".join(w if w.isupper() else w.capitalize() for w in words)


SECTION_MARKER = "--- Content from {url} ---"
_SECTION_RE = re.compile(r"^--- Content from (\S+) ---$", re.MULTILINE)


def build_aggregate(sections: Iterable[tuple[str, str]]) -> str:
    """Join per-document text into the combined snapshot the UI still reads."""
    return "\n\n".join(
        f"{SECTION_MARKER.format(url=url)}\n\n{text}" for url, text in sections
    )


def split_aggregate(aggregate: str) -> dict[str, str]:
    """Split a combined snapshot back into {url: text}.

    Used once per source to seed per-document snapshots from the pre-upgrade
    aggregates, so migrating does not throw away a year of baselines.
    """
    if not aggregate:
        return {}

    matches = list(_SECTION_RE.finditer(aggregate))
    if not matches:
        return {}

    sections: dict[str, str] = {}
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(aggregate)
        sections[match.group(1)] = aggregate[match.end():end].strip()
    return sections
