"""Tests for the one-off repair scripts in scripts/.

They are one-off in the sense that the damage they fix was done once, not in
the sense that they run once — each is idempotent and re-runnable, because the
alternative is a script nobody dares run twice. These tests pin that, and pin
the judgement each script encodes about what counts as damage.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO_ROOT)
sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))

import repair_legacy_analyses as repair  # noqa: E402


class LegacyAnalysesAreIdentifiedByTheMissingSchema(unittest.TestCase):
    def test_an_analysis_without_a_verdict_is_legacy(self):
        self.assertTrue(repair.is_legacy({"summary": "x", "priority": "low"}))

    def test_an_analysis_with_a_verdict_is_not(self):
        self.assertFalse(repair.is_legacy({"verdict": "material_change"}))


class OnlyGenuinelyWrongDatesAreRewritten(unittest.TestCase):
    """The pipeline writes date_time and last_amended microseconds apart, so an
    exact-match test would rewrite every legacy file on every run forever."""

    def test_a_model_invented_date_disagrees(self):
        self.assertTrue(
            repair.dates_disagree("2024-05-16T10:00:00Z", "2026-08-09T12:10:17+10:00")
        )

    def test_two_seconds_apart_is_the_same_event(self):
        self.assertFalse(
            repair.dates_disagree(
                "2026-03-17T23:07:59.853006+10:00", "2026-03-17T23:07:57.694614+10:00"
            )
        )

    def test_an_identical_date_does_not_disagree(self):
        stamp = "2026-08-09T12:10:17+10:00"
        self.assertFalse(repair.dates_disagree(stamp, stamp))

    def test_an_unparseable_date_is_replaced(self):
        self.assertTrue(repair.dates_disagree("Unknown", "2026-08-09T12:10:17+10:00"))

    def test_nothing_is_rewritten_when_the_pipeline_has_no_date_either(self):
        self.assertFalse(repair.dates_disagree("2024-05-16T10:00:00Z", None))


class PoisonedBaselinesAreThoseBelowTheValidationFloor(unittest.TestCase):
    """validate_capture never writes a length below min_length, so a stored
    length that is below it was written before the gate existed."""

    def setUp(self):
        sys.path.insert(0, os.path.join(REPO_ROOT, "scripts"))
        import reset_poisoned_baselines  # noqa: F401

        self.module = reset_poisoned_baselines

    def test_the_repaired_repository_has_no_poisoned_baselines_left(self):
        os.chdir(REPO_ROOT)
        self.assertEqual(self.module.reset(dry_run=True), 0)

    def test_every_stored_length_is_at_or_above_the_floor(self):
        from steward.config import load_config

        floor = load_config(os.path.join(REPO_ROOT, "steward_config.yaml")).validation.min_length
        with open(os.path.join(REPO_ROOT, "hashes.json"), encoding="utf-8") as handle:
            hashes = json.load(handle)

        for set_name, entry in hashes.items():
            for url, record in (entry.get("documents") or {}).items():
                length = record.get("length")
                if isinstance(length, int) and length > 0:
                    self.assertGreaterEqual(
                        length, floor, f"{set_name} / {url} has a {length}-char baseline"
                    )


class EveryConfiguredUrlHasARecordAndViceVersa(unittest.TestCase):
    """A URL removed from policy_sets.json leaves an orphan in hashes.json that
    nothing will ever clean up, and the health report keeps counting it."""

    def test_no_orphaned_document_records(self):
        with open(os.path.join(REPO_ROOT, "policy_sets.json"), encoding="utf-8") as handle:
            configured = {
                ps["setName"]: {u["url"] for u in ps.get("urls", [])}
                for ps in json.load(handle)
            }
        with open(os.path.join(REPO_ROOT, "hashes.json"), encoding="utf-8") as handle:
            hashes = json.load(handle)

        for set_name, entry in hashes.items():
            if set_name not in configured:
                continue
            stored = set((entry.get("documents") or {}).keys())
            orphans = stored - configured[set_name]
            self.assertEqual(orphans, set(), f"{set_name} has orphaned records: {orphans}")


if __name__ == "__main__":
    unittest.main()
