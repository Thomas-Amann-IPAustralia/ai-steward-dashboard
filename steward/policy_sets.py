"""The monitored-source list: loading, validation, and what "enabled" means.

This lived in `main.py` until anything other than the pipeline needed to write
`policy_sets.json`. The moment a second writer exists — an editor UI, a
migration script, a bulk import — a second copy of these rules appears with it,
and the two disagree the first time one is changed. One implementation, used by
the pipeline and by whatever else writes the file, is the whole point of this
module.

Pure: no file writes, no network, no logging side effects beyond the warnings
that explain a rejected entry. `main.py` remains the only thing that reads and
writes the datastore.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Tuple

log = logging.getLogger(__name__)

POLICY_SETS_FILE = "policy_sets.json"


def slugify_set_name(name: str) -> str:
    """The file_id a set's artefacts are named by.

    Stable by contract: it is the name of every snapshot, diff, analysis and
    archived log for the set, and `steward/history.py` parses it back out of
    those filenames. Changing this orphans the archive.
    """
    return re.sub(r"[^a-zA-Z0-9\-]+", "_", name).strip("_")


def validate_entry(policy_set: Any, index: int = 0) -> Tuple[bool, str]:
    """Whether one entry is usable, and why not if it isn't.

    Returns a reason rather than raising, because the pipeline skips a bad
    entry and carries on while an editor wants to show the reason to whoever
    typed it.
    """
    if not isinstance(policy_set, dict):
        return False, "not an object"

    name = policy_set.get("setName")
    if not name:
        return False, "missing 'setName'"
    if not isinstance(name, str):
        return False, "'setName' must be a string"
    if not policy_set.get("category"):
        return False, "missing 'category'"

    urls = policy_set.get("urls")
    if not isinstance(urls, list) or not urls:
        return False, "missing or empty 'urls'"
    if not all(isinstance(u, dict) and u.get("url") for u in urls):
        return False, "malformed url entry"

    if "enabled" in policy_set and not isinstance(policy_set["enabled"], bool):
        return False, "'enabled' must be true or false"

    return True, ""


def validate_policy_sets(policy_sets: list) -> list:
    """Every entry that is usable, with the rest logged and dropped.

    One malformed source must not stop the other seven being checked.
    """
    valid: List[dict] = []
    seen_names: set[str] = set()

    for i, policy_set in enumerate(policy_sets):
        ok, reason = validate_entry(policy_set, i)
        if not ok:
            label = policy_set.get("setName") if isinstance(policy_set, dict) else None
            log.warning(
                "Skipping policy_sets[%d]%s: %s", i, f" ({label})" if label else "", reason
            )
            continue

        name = policy_set["setName"]
        if name in seen_names:
            log.warning("Skipping policy_sets[%d] (%s): duplicate setName", i, name)
            continue

        seen_names.add(name)
        valid.append(policy_set)

    return valid


def is_enabled(policy_set: dict) -> bool:
    """A set is monitored unless it says otherwise."""
    return policy_set.get("enabled", True) is not False


def partition(policy_sets: List[dict]) -> Tuple[List[dict], List[dict]]:
    """(monitored, deliberately not monitored)."""
    return (
        [ps for ps in policy_sets if is_enabled(ps)],
        [ps for ps in policy_sets if not is_enabled(ps)],
    )


def disabled_entry(policy_set: dict, previous_entry: dict, timestamp: str) -> Dict[str, Any]:
    """State for a set that is deliberately not being checked.

    A source that cannot be read is a different thing from a source nobody is
    trying to read, and the dashboard has to be able to say which. The stored
    state is carried forward untouched so the archive still resolves; what
    changes is that health stops alerting on it and the UI stops presenting its
    last known reading as current.
    """
    entry = dict(previous_entry)
    entry.update(
        {
            "category": policy_set["category"],
            "urls": policy_set["urls"],
            "file_id": slugify_set_name(policy_set["setName"]),
            "monitoring": "disabled",
            "disabled_reason": (policy_set.get("disabled_reason") or "").strip()
            or "No reason recorded.",
            "disabled_since": previous_entry.get("disabled_since") or timestamp,
        }
    )
    return entry
