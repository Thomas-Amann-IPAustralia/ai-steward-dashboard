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

The schema is also handed to the API as a response schema, so the model is
constrained to it rather than merely asked; validation stays as the check.
An overloaded model (HTTP 503/429) is retried with a backoff instead of being
spent as the one schema retry — two of the three "schema failures" in
September 2026 were a 503 retried within the same second.
"""

from __future__ import annotations

import json
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

log = logging.getLogger(__name__)

PRIORITIES = ("critical", "high", "medium", "low")
VERDICTS = ("material_change", "no_material_change", "uncertain")

MATERIAL_CHANGE = "material_change"
NO_MATERIAL_CHANGE = "no_material_change"
UNCERTAIN = "uncertain"

# What a policy set is watched for. A `policy` binds the reader — terms of
# service, government policy — and its changes are rated for risk. An
# `adoption` set is a register of what other agencies are doing (the
# Commonwealth's list of AI transparency statements): worth keeping up with,
# but a change to it alters nobody's obligations, so it is described rather
# than rated, and always carries the lowest priority.
POLICY = "policy"
ADOPTION = "adoption"
SET_KINDS = (POLICY, ADOPTION)

_FENCE = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.MULTILINE)

# Status codes worth waiting out rather than giving up on.
TRANSIENT_STATUS = {429, 500, 502, 503, 504}
# Seconds to wait before each successive retry of a transient API error.
TRANSIENT_BACKOFF = (15, 45, 90)

RESPONSE_SCHEMA = {
    "type": "OBJECT",
    "properties": {
        "verdict": {"type": "STRING", "enum": list(VERDICTS)},
        "summary": {"type": "STRING"},
        "analysis": {"type": "STRING"},
        "priority": {"type": "STRING", "enum": list(PRIORITIES)},
    },
    "required": ["verdict", "summary", "analysis", "priority"],
}


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
    # True when the model could not be reached at all, as opposed to
    # answering outside the schema.
    unavailable: bool = False

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

ADOPTION_PROMPT_TEMPLATE = """You are an AI policy analyst helping Australian public \
servants keep up with how the rest of the Australian Government is adopting AI.

A monitored register named "{set_name}" has changed. It records what other \
government entities have published — it is not a policy, and a change to it \
places no new obligation on the reader. Below is the unified diff between the \
stored version and the current one. Lines beginning with `-` were removed; \
lines beginning with `+` were added. Unmarked lines are surrounding context \
and did not change.

{documents_note}{fingerprint_note}
Respond with a single JSON object and nothing else:

{{
  "verdict": "One of: material_change, no_material_change, uncertain",
  "summary": "1-2 sentences in plain language: which entities were added, removed \
or renamed, or what else changed",
  "analysis": "Markdown covering: 1) entities added, removed or renamed, each named \
in full, 2) any change to the register's own text, such as counts, deadlines or \
compliance statements, 3) what this suggests about AI adoption across government, \
4) anything worth a closer look",
  "priority": "low"
}}

Verdict definitions:
- **material_change**: an entity was added, removed or renamed, or the register's \
own text changed in meaning.
- **no_material_change**: the diff is formatting, reordering, typography or \
boilerplate with no change in meaning. Say so plainly — do not manufacture \
significance.
- **uncertain**: the diff is too fragmentary or ambiguous to judge. Explain what \
you would need to see.

Always set priority to "low". Do not include a timestamp. Do not include any \
key other than the four above.

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
    kind: str = POLICY,
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

    template = ADOPTION_PROMPT_TEMPLATE if kind == ADOPTION else PROMPT_TEMPLATE
    return template.format(
        set_name=set_name,
        documents_note=documents_note,
        fingerprint_note=fingerprint_note,
        diff=diff_text,
    )


def parse_and_validate(raw_text: str, kind: str = POLICY) -> dict:
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
    if verdict == NO_MATERIAL_CHANGE or kind == ADOPTION:
        # The model occasionally declines and then rates the change anyway;
        # and a register of what others are doing is never a risk to rate.
        priority = "low"

    return {
        "verdict": verdict,
        "summary": parsed["summary"].strip(),
        "analysis": parsed["analysis"].strip(),
        "priority": priority,
    }


def is_transient(exc: Exception) -> bool:
    """Whether an API error is load or rate limiting rather than a real fault."""
    code = getattr(exc, "code", None)
    if isinstance(code, int) and code in TRANSIENT_STATUS:
        return True
    text = str(exc).upper()
    return any(marker in text for marker in ("UNAVAILABLE", "RESOURCE_EXHAUSTED", "DEADLINE_EXCEEDED"))


def generate_json(
    client,
    model: str,
    prompt: str,
    schema: dict,
    *,
    sleep: Callable[[float], None] = time.sleep,
    backoff: Sequence[float] = TRANSIENT_BACKOFF,
):
    """One structured-output call, waiting out transient overloads.

    Raises the last exception if the API never answers.
    """
    from google.genai import types

    config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=schema,
    )
    waits = list(backoff)
    while True:
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as exc:  # noqa: BLE001 — classified below
            if not waits or not is_transient(exc):
                raise
            delay = waits.pop(0)
            log.warning("  Model busy (%s) — retrying in %ss", type(exc).__name__, delay)
            sleep(delay)


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
    kind: str = POLICY,
    client=None,
    sleep: Callable[[float], None] = time.sleep,
) -> AnalysisOutcome:
    """Call the model, validate, retry once, then give up cleanly."""
    if client is None:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return AnalysisOutcome(error="GEMINI_API_KEY is not set", unavailable=True)
        from google import genai

        client = genai.Client(api_key=api_key)

    prompt = build_prompt(set_name, diff_text, changed_documents, tags, kind)
    outcome = AnalysisOutcome()
    last_error = ""

    for attempt in (1, 2):
        outcome.attempts = attempt
        text = prompt if attempt == 1 else prompt + _RETRY_SUFFIX.format(error=last_error)

        try:
            response = generate_json(client, model, text, RESPONSE_SCHEMA, sleep=sleep)
        except Exception as exc:  # noqa: BLE001 — an API failure must not kill the run
            last_error = f"{type(exc).__name__}: {exc}"
            log.error("  Gemini API error on attempt %d: %s", attempt, last_error)
            outcome.error = last_error
            if is_transient(exc):
                # Already waited out; a second round would only wait again.
                outcome.unavailable = True
                break
            continue

        prompt_tokens, output_tokens = _usage(response)
        outcome.prompt_tokens += prompt_tokens
        outcome.output_tokens += output_tokens
        raw = getattr(response, "text", "") or ""
        outcome.raw = raw

        try:
            outcome.result = parse_and_validate(raw, kind)
            outcome.error = ""
            return outcome
        except SchemaError as exc:
            last_error = str(exc)
            outcome.error = last_error
            log.warning("  Model response rejected on attempt %d: %s", attempt, last_error)

    log.error("  Giving up on '%s' after %d attempt(s): %s", set_name, outcome.attempts, outcome.error)
    return outcome
