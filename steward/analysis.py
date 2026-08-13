"""The one expensive call, and the schema contract around it.

Three properties the previous implementation lacked:

* The timestamp is stamped in code. The model does not know what time it is
  and, when asked, invented one — which is how the live Perplexity analysis
  came to be dated 16 May 2024.
* The response is validated. A missing key used to be backfilled with the
  string 'Unknown' and `priority` was never checked against the four
  permitted values, which is how a `priority: unknown` analysis reached the
  archive. Now: validate, retry once with the error, log and skip on the
  second failure.
* The model may decline. It was already writing "there are no changes between
  the provided documents" and then being forced to pick a priority anyway.
  `no_material_change` says that cleanly, and when it does the set is not
  badged and `last_amended` is not touched.
"""

from __future__ import annotations

import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional, Sequence

log = logging.getLogger(__name__)

PRIORITIES = ("critical", "high", "medium", "low")
VERDICTS = ("material_change", "no_material_change", "uncertain")

MATERIAL_CHANGE = "material_change"
NO_MATERIAL_CHANGE = "no_material_change"
UNCERTAIN = "uncertain"

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)


class SchemaError(ValueError):
    """The model's response did not satisfy the contract."""


@dataclass
class AnalysisOutcome:
    result: Optional[dict] = None
    error: str = ""
    attempts: int = 0
    prompt_tokens: int = 0
    output_tokens: int = 0
    raw: str = ""

    @property
    def ok(self) -> bool:
        return self.result is not None


PROMPT_TEMPLATE = """You are an AI policy analyst advising Australian public servants on \
changes to Terms of Service, privacy policies and government AI policy.

A monitored policy set named "{set_name}" has changed. Below is the unified diff \
between the stored version and the current one. Lines beginning with `-` were \
removed; lines beginning with `+` were added. Unmarked lines are surrounding \
context and did not change.

{documents_note}{fingerprint_note}
Respond with a single JSON object and nothing else:

{{
  "verdict": "One of: material_change, no_material_change, uncertain",
  "summary": "1-2 sentences in plain language describing what changed",
  "analysis": "Markdown covering: 1) what specifically changed, 2) who is affected, \
3) whether user rights, data handling or liability are affected, 4) any action required",
  "priority": "One of: critical, high, medium, low"
}}

Verdict definitions:
- **material_change**: the wording that changed alters meaning, obligations or rights.
- **no_material_change**: the diff is formatting, reordering, typography or \
boilerplate with no change in meaning. Say so plainly — do not manufacture \
significance. Set priority to "low".
- **uncertain**: the diff is too fragmentary or ambiguous to judge. Explain what \
you would need to see.

Priority definitions (they describe the change, not the document):
- **critical**: directly alters user rights, data handling, liability or legal obligations.
- **high**: significant shift in how the service operates or is governed.
- **medium**: notable but non-urgent — clarifications, minor scope adjustments.
- **low**: cosmetic, formatting or trivial wording with no practical impact.

Do not include a timestamp. Do not include any key other than the four above.

UNIFIED DIFF:
---
{diff}
---"""

_RETRY_SUFFIX = """

Your previous response was rejected: {error}

Return only the JSON object described above, with all four keys present and \
"verdict" and "priority" drawn from the permitted values."""


def build_prompt(
    set_name: str,
    diff_text: str,
    changed_documents: Sequence[str] = (),
    tags: Sequence[str] = (),
) -> str:
    documents_note = ""
    if changed_documents:
        listed = ", ".join(changed_documents)
        documents_note = (
            f"Documents in this set that changed: {listed}. "
            "Other documents in the set were checked and are unchanged.\n\n"
        )

    fingerprint_note = ""
    if tags:
        fingerprint_note = (
            f"A pattern scan of the changed lines flagged: {', '.join(tags)}. "
            "Treat this as a hint about where to look, not as a conclusion.\n\n"
        )

    return PROMPT_TEMPLATE.format(
        set_name=set_name,
        documents_note=documents_note,
        fingerprint_note=fingerprint_note,
        diff=diff_text,
    )


def parse_and_validate(raw_text: str) -> dict:
    """Parse the model's reply and enforce the schema, or raise SchemaError."""
    if not raw_text or not raw_text.strip():
        raise SchemaError("response was empty")

    cleaned = _FENCE.sub("", raw_text).strip()
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise SchemaError(f"response was not valid JSON ({exc})") from exc

    if not isinstance(parsed, dict):
        raise SchemaError(f"expected a JSON object, got {type(parsed).__name__}")

    missing = [key for key in ("verdict", "summary", "analysis", "priority") if key not in parsed]
    if missing:
        raise SchemaError(f"missing required key(s): {', '.join(missing)}")

    verdict = parsed["verdict"]
    if not isinstance(verdict, str) or verdict.strip().lower() not in VERDICTS:
        raise SchemaError(f"verdict must be one of {', '.join(VERDICTS)}, got {verdict!r}")

    priority = parsed["priority"]
    if not isinstance(priority, str) or priority.strip().lower() not in PRIORITIES:
        raise SchemaError(f"priority must be one of {', '.join(PRIORITIES)}, got {priority!r}")

    for key in ("summary", "analysis"):
        if not isinstance(parsed[key], str) or not parsed[key].strip():
            raise SchemaError(f"{key} must be a non-empty string")

    verdict = verdict.strip().lower()
    priority = priority.strip().lower()
    if verdict == NO_MATERIAL_CHANGE:
        # The model occasionally declines and then rates the change anyway.
        priority = "low"

    return {
        "verdict": verdict,
        "summary": parsed["summary"].strip(),
        "analysis": parsed["analysis"].strip(),
        "priority": priority,
    }


def _usage(response) -> tuple[int, int]:
    usage = getattr(response, "usage_metadata", None)
    if usage is None:
        return 0, 0
    return (
        int(getattr(usage, "prompt_token_count", 0) or 0),
        int(getattr(usage, "candidates_token_count", 0) or 0),
    )


def analyse_change(
    set_name: str,
    diff_text: str,
    *,
    model: str,
    changed_documents: Sequence[str] = (),
    tags: Sequence[str] = (),
    client=None,
) -> AnalysisOutcome:
    """Call the model, validate, retry once, then give up cleanly."""
    from google import genai
    from google.genai import types

    api_key = os.environ.get("GEMINI_API_KEY")
    if client is None:
        if not api_key:
            return AnalysisOutcome(error="GEMINI_API_KEY is not set")
        client = genai.Client(api_key=api_key)

    prompt = build_prompt(set_name, diff_text, changed_documents, tags)
    outcome = AnalysisOutcome()
    last_error = ""

    for attempt in (1, 2):
        outcome.attempts = attempt
        text = prompt if attempt == 1 else prompt + _RETRY_SUFFIX.format(error=last_error)

        try:
            response = client.models.generate_content(
                model=model,
                contents=text,
                config=types.GenerateContentConfig(response_mime_type="application/json"),
            )
        except Exception as exc:  # noqa: BLE001 — an API failure must not kill the run
            last_error = f"{type(exc).__name__}: {exc}"
            log.error("  Gemini API error on attempt %d: %s", attempt, last_error)
            outcome.error = last_error
            continue

        prompt_tokens, output_tokens = _usage(response)
        outcome.prompt_tokens += prompt_tokens
        outcome.output_tokens += output_tokens
        raw = getattr(response, "text", "") or ""
        outcome.raw = raw

        try:
            outcome.result = parse_and_validate(raw)
            outcome.error = ""
            return outcome
        except SchemaError as exc:
            last_error = str(exc)
            outcome.error = last_error
            log.warning("  Model response rejected on attempt %d: %s", attempt, last_error)

    log.error("  Giving up on '%s' after 2 attempts: %s", set_name, outcome.error)
    return outcome
