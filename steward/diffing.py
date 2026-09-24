"""Diff generation, the cosmetic gate, and the significance fingerprint.

The cosmetic gate compares *what the text says*, not how it is typeset. Each
changed block of lines is reduced to a canonical form — case, quote style,
dash style, spacing around punctuation and line wrapping all folded away —
and a block whose canonical form did not move is put back as unchanged
before the diff is built. If nothing substantive is left, the change stops
here: no model call, `last_amended` untouched. Six of the eleven model calls
between August and September 2026 were spent on exactly this kind of diff
(an em dash gaining spaces, a paragraph re-wrapped) and came back
`no_material_change`.

Only a substantive diff proceeds, and what proceeds is the diff itself rather
than two 50,000-character documents — which is both an order of magnitude
fewer tokens and a sharper analysis, because the model is told where to look.

The fingerprint tags changed lines with the things a steward cares about and
hands them to the model as context. It is never a gate: a genuine content
change is analysed whether or not it matches anything on the watchlist.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Sequence

# Tag patterns, scanned across changed lines only.
_PATTERNS = {
    "money": re.compile(r"(?:[$€£]\s?\d[\d,]*(?:\.\d+)?|\b\d[\d,]*(?:\.\d+)?\s?(?:AUD|USD|EUR|GBP)\b)"),
    "date": re.compile(
        r"\b(?:\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)"
        r"|(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2}"
        r"|\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4})\b",
        re.IGNORECASE,
    ),
    "percentage": re.compile(r"\b\d+(?:\.\d+)?\s?%"),
    "duration": re.compile(r"\b\d+\s+(?:days?|months?|years?|business days?)\b", re.IGNORECASE),
    "section_reference": re.compile(
        r"\b(?:section|clause|article|schedule|appendix|paragraph)\s+\d+(?:\.\d+)*\b", re.IGNORECASE
    ),
    "obligation": re.compile(
        r"\b(?:must not|shall not|will not|may not|must|shall|may|will be required to)\b", re.IGNORECASE
    ),
}


# Typographic variants that never change meaning, folded for comparison only.
_CANONICAL_FOLD = str.maketrans(
    {
        "\u2018": "'", "\u2019": "'", "\u201a": "'", "\u201b": "'", "\u2032": "'", "`": "'",
        "\u201c": '"', "\u201d": '"', "\u201e": '"', "\u2033": '"',
        "\u2010": "-", "\u2011": "-", "\u2012": "-", "\u2013": "-", "\u2014": "-",
        "\u2015": "-", "\u2212": "-",
        "\u2022": "-", "\u2023": "-", "\u25aa": "-", "\u25cf": "-", "\u00b7": "-",
        "\u2026": "...",
    }
)
# How a link is written ("www.afca.org.au" vs "https://www.afca.org.au/") is
# presentation; where it points is not, so only the decoration is dropped.
_URL_DECORATION = re.compile(r"https?://|\bwww\.", re.IGNORECASE)
_TRAILING_SLASH = re.compile(r"/(?=\s|$)")
_ANY_WHITESPACE = re.compile(r"\s+")
_SPACE_AROUND_PUNCT = re.compile(r"\s*([-,.;:!?()\[\]{}/'\"*|])\s*")


def canonical(text: str) -> str:
    """What a passage says, with every purely typographic choice folded away.

    Lossy by design and never stored or shown: it exists only to decide
    whether two passages differ in anything but presentation.
    """
    text = unicodedata.normalize("NFKC", text or "")
    text = text.translate(_CANONICAL_FOLD).casefold()
    text = _URL_DECORATION.sub("", text)
    text = _TRAILING_SLASH.sub("", text)
    text = _ANY_WHITESPACE.sub(" ", text)
    text = _SPACE_AROUND_PUNCT.sub(r"\1", text)
    return text.strip()


def is_cosmetic(old_text: str, new_text: str) -> bool:
    """True when two texts differ only in presentation."""
    return canonical(old_text) == canonical(new_text)


@dataclass
class DiffResult:
    text: str = ""
    added: int = 0
    removed: int = 0
    truncated: bool = False
    tags: list[str] = field(default_factory=list)
    # Lines that moved but only cosmetically, and were kept out of the diff.
    cosmetic_lines: int = 0

    @property
    def is_empty(self) -> bool:
        return self.added == 0 and self.removed == 0

    @property
    def changed_lines(self) -> int:
        return self.added + self.removed


def changed_lines_of(diff_text: str) -> list[str]:
    """Content lines a diff added or removed, without the +/- marker."""
    lines = []
    for line in diff_text.splitlines():
        if line.startswith(("+++", "---", "@@")):
            continue
        if line.startswith(("+", "-")):
            lines.append(line[1:])
    return lines


def fingerprint(diff_text: str, watchlist: Sequence[str] = ()) -> list[str]:
    """Tags describing what kind of thing moved, for the model's context."""
    changed = "\n".join(changed_lines_of(diff_text))
    if not changed.strip():
        return []

    tags = [name for name, pattern in _PATTERNS.items() if pattern.search(changed)]

    lowered = changed.lower()
    hits = sorted({term for term in watchlist if term.lower() in lowered})
    tags.extend(f"watchlist:{term}" for term in hits)
    return tags


def compute_diff(
    old_text: str,
    new_text: str,
    *,
    label: str = "document",
    context_lines: int = 3,
    max_chars: int = 40000,
    watchlist: Sequence[str] = (),
) -> DiffResult:
    """Unified diff of the substantive changes between two normalised documents.

    Blocks that changed only cosmetically are restored to their stored
    wording before diffing, so they neither reach the model nor dilute the
    diff a steward reads. `cosmetic_lines` records how much was set aside.
    """
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    effective, cosmetic_lines = _set_aside_cosmetic_blocks(old_lines, new_lines)

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            effective,
            fromfile=f"{label} (stored)",
            tofile=f"{label} (current)",
            lineterm="",
            n=context_lines,
        )
    )

    added = sum(1 for line in diff_lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff_lines if line.startswith("-") and not line.startswith("---"))

    text = "\n".join(diff_lines)
    truncated = False
    if len(text) > max_chars:
        text = text[:max_chars] + "\n… diff truncated …"
        truncated = True

    return DiffResult(
        text=text,
        added=added,
        removed=removed,
        truncated=truncated,
        tags=fingerprint(text, watchlist),
        cosmetic_lines=cosmetic_lines,
    )


def _set_aside_cosmetic_blocks(old_lines: list[str], new_lines: list[str]) -> tuple[list[str], int]:
    """The new document with cosmetic-only blocks put back to their old form.

    A re-wrapped paragraph or a re-typeset dash is one block to the line
    matcher; comparing each block's canonical form decides whether anything
    in it was actually said differently. A whole document that is only
    re-flowed is caught up front, since re-wrapping can move text across
    block boundaries.
    """
    if is_cosmetic("\n".join(old_lines), "\n".join(new_lines)):
        return list(old_lines), sum(
            1 for line in difflib.ndiff(old_lines, new_lines) if line[:1] in "+-"
        )

    matcher = difflib.SequenceMatcher(None, old_lines, new_lines, autojunk=False)
    effective: list[str] = []
    cosmetic_lines = 0
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        old_block, new_block = old_lines[i1:i2], new_lines[j1:j2]
        if tag == "equal":
            effective.extend(new_block)
            continue
        restored, set_aside = _peel_cosmetic_edges(old_block, new_block)
        effective.extend(restored)
        cosmetic_lines += set_aside
    return effective, cosmetic_lines


# How many lines either side may be grouped when matching a re-wrapped run.
_PEEL_WINDOW = 4


def _peel_cosmetic_edges(old_block: list[str], new_block: list[str]) -> tuple[list[str], int]:
    """Restore cosmetic runs at the start and end of one changed block.

    The line matcher happily groups a re-wrapped paragraph with a genuine
    edit on the next line into a single block. Peeling matching runs off
    each end leaves only the lines whose wording actually moved.
    """
    if is_cosmetic("\n".join(old_block), "\n".join(new_block)):
        return list(old_block), max(len(old_block), len(new_block))

    head: list[str] = []
    tail: list[str] = []
    set_aside = 0
    oi, oj = 0, len(old_block)
    ni, nj = 0, len(new_block)

    def match(old_run: list[str], new_run: list[str]) -> bool:
        return bool(old_run or new_run) and is_cosmetic("\n".join(old_run), "\n".join(new_run))

    progressed = True
    while progressed and oi < oj and ni < nj:
        progressed = False
        for a in range(1, min(_PEEL_WINDOW, oj - oi) + 1):
            for b in range(1, min(_PEEL_WINDOW, nj - ni) + 1):
                if match(old_block[oi:oi + a], new_block[ni:ni + b]):
                    head.extend(old_block[oi:oi + a])
                    set_aside += max(a, b)
                    oi, ni = oi + a, ni + b
                    progressed = True
                    break
            if progressed:
                break

    progressed = True
    while progressed and oi < oj and ni < nj:
        progressed = False
        for a in range(1, min(_PEEL_WINDOW, oj - oi) + 1):
            for b in range(1, min(_PEEL_WINDOW, nj - ni) + 1):
                if match(old_block[oj - a:oj], new_block[nj - b:nj]):
                    tail[:0] = old_block[oj - a:oj]
                    set_aside += max(a, b)
                    oj, nj = oj - a, nj - b
                    progressed = True
                    break
            if progressed:
                break

    return head + new_block[ni:nj] + tail, set_aside


def combine_diffs(per_document: Sequence[tuple[str, DiffResult]]) -> str:
    """One diff artefact per policy set, sectioned by document."""
    blocks = []
    for label, result in per_document:
        if result.is_empty:
            continue
        header = f"===== {label} — +{result.added} / -{result.removed} ====="
        blocks.append(f"{header}\n{result.text}")
    return "\n\n".join(blocks)
