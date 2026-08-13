"""Content plausibility checks — reject implausible scrapes before they
become changes.

Every capture passes through here before it is allowed to overwrite a stored
snapshot or reach the model. A capture that fails is recorded as a
`suspect_scrape`: the snapshot is left alone, no analysis is run, and the
source is flagged for the steward. Nothing is silently accepted.

The 8 August 2026 Perplexity capture fails three of these checks at once — it
was 354 bytes of Chrome error page against a 57 kB stored document — and the
false critical that followed it, plus the false "restored" critical on
9 August, both disappear.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence

from .content import fold_for_matching

# Verdict codes, ordered roughly by how early they fire.
EMPTY = "empty"
TOO_SHORT = "too_short"
BLOCK_PAGE = "block_page"
SHRANK = "shrank"
GREW = "grew"


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    reason: Optional[str] = None
    detail: str = ""

    def __bool__(self) -> bool:
        return self.ok


VALID = ValidationResult(True)


def check_failure_signature(text: str, signatures: Sequence[str]) -> Optional[str]:
    """Return the signature a block page matched, or None.

    Matching happens on a quote-folded, case-folded copy so that typographic
    apostrophes cannot smuggle an error page past the list.
    """
    folded = fold_for_matching(text)
    for signature in signatures:
        if fold_for_matching(signature) in folded:
            return signature
    return None


def validate_capture(
    text: Optional[str],
    prior_length: Optional[int],
    *,
    min_length: int,
    shrink_ratio: float,
    growth_ratio: float,
    failure_signatures: Sequence[str],
) -> ValidationResult:
    """Decide whether a freshly captured document is plausibly the real thing.

    `prior_length` is the stored length for this same URL, or None on a first
    capture — a first capture has nothing to compare against, so only the
    absolute checks apply.
    """
    if not text or not text.strip():
        return ValidationResult(False, EMPTY, "extraction produced no text")

    length = len(text)

    signature = check_failure_signature(text, failure_signatures)
    if signature is not None:
        return ValidationResult(
            False, BLOCK_PAGE, f"matched failure signature {signature!r}"
        )

    if length < min_length:
        return ValidationResult(
            False,
            TOO_SHORT,
            f"{length} chars is below the {min_length} char minimum",
        )

    if prior_length:
        floor = prior_length * shrink_ratio
        ceiling = prior_length * growth_ratio
        if length < floor:
            return ValidationResult(
                False,
                SHRANK,
                f"{length} chars is {length / prior_length:.0%} of the stored "
                f"{prior_length} chars, below the {shrink_ratio:.0%} floor",
            )
        if length > ceiling:
            return ValidationResult(
                False,
                GREW,
                f"{length} chars is {length / prior_length:.0%} of the stored "
                f"{prior_length} chars, above the {growth_ratio:.0%} ceiling",
            )

    return VALID
