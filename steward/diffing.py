"""Diff generation, the cosmetic gate, and the significance fingerprint.

Two documents whose normalised text is identical produce an empty diff. That
is the cosmetic gate: stop, no model call, `last_amended` untouched. Only a
non-empty diff proceeds, and what proceeds is the diff itself rather than two
50,000-character documents — which is both an order of magnitude fewer tokens
and a sharper analysis, because the model is told where to look.

The fingerprint tags changed lines with the things a steward cares about and
hands them to the model as context. It is never a gate: a genuine content
change is analysed whether or not it matches anything on the watchlist.
"""

from __future__ import annotations

import difflib
import re
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


@dataclass
class DiffResult:
    text: str = ""
    added: int = 0
    removed: int = 0
    truncated: bool = False
    tags: list[str] = field(default_factory=list)

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
    """Unified diff of two already-normalised documents."""
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()

    diff_lines = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
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
    )


def combine_diffs(per_document: Sequence[tuple[str, DiffResult]]) -> str:
    """One diff artefact per policy set, sectioned by document."""
    blocks = []
    for label, result in per_document:
        if result.is_empty:
            continue
        header = f"===== {label} — +{result.added} / -{result.removed} ====="
        blocks.append(f"{header}\n{result.text}")
    return "\n\n".join(blocks)
