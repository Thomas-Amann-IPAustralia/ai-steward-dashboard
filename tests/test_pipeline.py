"""Tests that lock in the behaviour the upgrade exists to guarantee.

Not a coverage push. Each test pins one property that, when it broke, put a
false alert on the dashboard:

* normalisation is idempotent, so a stored snapshot does not drift on re-read;
* a cosmetic diff produces no model call;
* the size-delta guard rejects the 8 August 2026 Perplexity capture, using the
  archived file itself as the fixture;
* schema validation rejects an out-of-enum priority.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from steward import PIPELINE_VERSION, analysis, config, content, diffing, fetching, health, history
from steward.validation import BLOCK_PAGE, SHRANK, TOO_SHORT, validate_capture

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERPLEXITY_8_AUG = os.path.join(
    REPO_ROOT, "logs", "Perplexity_AI_Legal_Policies_20260808_120221_snapshot.txt"
)
PERPLEXITY_7_AUG = os.path.join(
    REPO_ROOT, "logs", "Perplexity_AI_Legal_Policies_20260807_125653_snapshot.txt"
)
TOS_URL = "https://www.perplexity.ai/hub/legal/terms-of-service"


def read_fixture(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def load_cfg():
    return config.load_config(os.path.join(REPO_ROOT, "steward_config.yaml"))



def first_alert_body(report):
    """The alert body as it reads the first time these alerts are seen.

    Alerts fire on transitions now, so rendering one needs a before-state as
    well as a report. An empty state is "nothing has ever been reported", which
    is what these tests are describing.
    """
    empty = {"open": {}, "last_digest_at": None}
    return health.render_alert_markdown(health.diff_alerts(empty, report), report)

class NormalisationIsIdempotent(unittest.TestCase):
    def test_repeated_normalisation_is_a_no_op(self):
        raw = (
            "Terms   of Service\r\n\r\n\r\n\r\n"
            "We may   share &amp;amp; disclose your data.​\n"
            "  Effective\t1 July 2026  \n"
        )
        once = content.normalise(raw)
        self.assertEqual(once, content.normalise(once))
        self.assertEqual(once, content.normalise(content.normalise(once)))

    def test_normalisation_is_idempotent_on_a_real_archived_snapshot(self):
        raw = read_fixture(PERPLEXITY_7_AUG)
        once = content.normalise(raw)
        self.assertTrue(once)
        self.assertEqual(once, content.normalise(once))

    def test_hash_is_stable_across_cosmetic_variation(self):
        a = content.normalise("Section 3.  Payment  terms &amp; conditions.")
        b = content.normalise("Section 3.   Payment terms &amp;amp; conditions.\r\n")
        self.assertEqual(content.content_hash(a), content.content_hash(b))


class CosmeticDiffMakesNoModelCall(unittest.TestCase):
    """The 7 August 2026 run — a paid call that returned "no changes" — has to
    die at the cosmetic gate rather than reaching the model."""

    def setUp(self):
        self.cfg = load_cfg()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self._cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, self._cwd)
        main.setup_directories()

    def _fake_fetch(self, text):
        def fetch(url_data, prior, cfg, policy_set=None):
            return fetching.FetchResult(
                url_data["url"],
                fetching.OK,
                text=text,
                extractor=fetching.EXTRACTOR_TRAFILATURA,
            )

        return fetch

    def test_whitespace_only_change_is_not_a_change(self):
        stored = "Clause 1. You may not resell the service.\n\nClause 2. Fees are billed monthly."
        body = stored + "\n" + "Filler sentence about the service. " * 40

        file_id = "Fixture_Set"
        doc_id = content.document_id(TOS_URL)
        main.write_text(main.document_snapshot_path(file_id, doc_id), content.normalise(body))

        prior = {
            "doc_id": doc_id,
            "hash": content.content_hash(content.normalise(body)),
            "length": len(content.normalise(body)),
            "pipeline_version": PIPELINE_VERSION,
            "consecutive_failures": 0,
        }

        # Same document, re-rendered with non-breaking spaces, entity
        # double-encoding, CRLF line endings and a run of blank lines.
        cosmetic = body.replace(" ", " ", 12).replace("\n", "\r\n") + "\n\n\n\n"

        original = fetching.fetch_document
        fetching.fetch_document = self._fake_fetch(cosmetic)
        self.addCleanup(setattr, fetching, "fetch_document", original)

        record, outcome, diff, _ = main.process_document(
            {"url": TOS_URL}, {}, file_id, prior, self.cfg, "2026-08-07T12:56:53+10:00"
        )

        self.assertEqual(outcome, main.DOC_UNCHANGED)
        self.assertIsNone(diff, "a cosmetic re-render must not produce a diff to analyse")
        self.assertEqual(record["hash"], prior["hash"])

    def test_a_real_edit_still_produces_a_diff(self):
        body = "Clause 1. You may not resell the service.\n" + "Filler. " * 200
        edited = body.replace("may not resell", "may resell, subject to a 30% fee,")

        file_id = "Fixture_Set"
        doc_id = content.document_id(TOS_URL)
        main.write_text(main.document_snapshot_path(file_id, doc_id), content.normalise(body))
        prior = {
            "doc_id": doc_id,
            "hash": content.content_hash(content.normalise(body)),
            "length": len(content.normalise(body)),
            "pipeline_version": PIPELINE_VERSION,
            "consecutive_failures": 0,
        }

        original = fetching.fetch_document
        fetching.fetch_document = self._fake_fetch(edited)
        self.addCleanup(setattr, fetching, "fetch_document", original)

        record, outcome, diff, _ = main.process_document(
            {"url": TOS_URL}, {}, file_id, prior, self.cfg, "2026-08-07T12:56:53+10:00"
        )

        self.assertEqual(outcome, main.DOC_CHANGED)
        self.assertIsNotNone(diff)
        self.assertFalse(diff.is_empty)
        # The fingerprint is context for the model, never a veto — but it
        # should notice a percentage appearing in a changed line.
        self.assertIn("percentage", diff.tags)


class SizeDeltaGuardRejectsThe8AugustCapture(unittest.TestCase):
    """The capture that produced two false criticals, replayed from logs/."""

    def setUp(self):
        self.cfg = load_cfg()
        aggregate = read_fixture(PERPLEXITY_8_AUG)
        self.sections = content.split_aggregate(aggregate)
        self.tos = content.normalise(self.sections[TOS_URL])

    def test_the_archive_really_does_contain_the_bad_capture(self):
        self.assertIn(TOS_URL, self.sections)
        self.assertLess(len(self.tos), 500, "fixture should be the truncated error page")

    def test_the_old_failure_signature_check_missed_it(self):
        """Chrome renders a typographic apostrophe, and the straight-quote
        signature never matched. That is how the block page got through."""
        self.assertNotIn("This site can't be reached", self.sections[TOS_URL])
        self.assertIn("This site can’t be reached", self.sections[TOS_URL])

    def test_quote_folded_signature_check_catches_it(self):
        result = validate_capture(
            self.tos,
            None,
            min_length=self.cfg.validation.min_length,
            shrink_ratio=self.cfg.validation.shrink_ratio,
            growth_ratio=self.cfg.validation.growth_ratio,
            failure_signatures=self.cfg.validation.failure_signatures,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, BLOCK_PAGE)

    def test_size_delta_guard_rejects_it_independently(self):
        """Even with every failure signature removed, 354 bytes against a
        57 kB stored document is not a policy that shrank — it is a bad read."""
        stripped = "Perplexity Terms of Service. " * 12  # ~350 chars, no signatures
        result = validate_capture(
            stripped,
            56982,
            min_length=0,  # isolate the delta guard from the length floor
            shrink_ratio=self.cfg.validation.shrink_ratio,
            growth_ratio=self.cfg.validation.growth_ratio,
            failure_signatures=self.cfg.validation.failure_signatures,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, SHRANK)

    def test_minimum_length_rejects_it_too(self):
        result = validate_capture(
            "Perplexity Terms of Service.",
            None,
            min_length=self.cfg.validation.min_length,
            shrink_ratio=self.cfg.validation.shrink_ratio,
            growth_ratio=self.cfg.validation.growth_ratio,
            failure_signatures=self.cfg.validation.failure_signatures,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.reason, TOO_SHORT)

    def test_an_unchanged_sibling_document_is_untouched(self):
        """Privacy and AUP were byte-identical on 7, 8 and 9 August. Per-URL
        hashing is what stops one bad URL looking like the whole set moved."""
        seventh = content.split_aggregate(read_fixture(PERPLEXITY_7_AUG))
        for url in ("https://www.perplexity.ai/hub/legal/privacy-policy",
                    "https://www.perplexity.ai/hub/legal/aup"):
            self.assertEqual(
                content.content_hash(content.normalise(seventh[url])),
                content.content_hash(content.normalise(self.sections[url])),
                f"{url} should hash identically across the two runs",
            )


class SchemaValidationRejectsBadResponses(unittest.TestCase):
    def test_out_of_enum_priority_is_rejected(self):
        raw = json.dumps(
            {
                "verdict": "material_change",
                "summary": "Something changed.",
                "analysis": "## Detail",
                "priority": "unknown",
            }
        )
        with self.assertRaises(analysis.SchemaError) as caught:
            analysis.parse_and_validate(raw)
        self.assertIn("priority", str(caught.exception))

    def test_out_of_enum_verdict_is_rejected(self):
        raw = json.dumps(
            {
                "verdict": "probably_fine",
                "summary": "Something changed.",
                "analysis": "## Detail",
                "priority": "low",
            }
        )
        with self.assertRaises(analysis.SchemaError):
            analysis.parse_and_validate(raw)

    def test_missing_key_is_rejected_rather_than_backfilled(self):
        raw = json.dumps({"verdict": "material_change", "summary": "x", "priority": "low"})
        with self.assertRaises(analysis.SchemaError) as caught:
            analysis.parse_and_validate(raw)
        self.assertIn("analysis", str(caught.exception))

    def test_declining_forces_low_priority(self):
        raw = json.dumps(
            {
                "verdict": "no_material_change",
                "summary": "Formatting only.",
                "analysis": "Nothing of substance moved.",
                "priority": "critical",
            }
        )
        parsed = analysis.parse_and_validate(raw)
        self.assertEqual(parsed["verdict"], analysis.NO_MATERIAL_CHANGE)
        self.assertEqual(parsed["priority"], "low")

    def test_fenced_json_is_accepted(self):
        raw = '```json\n{"verdict": "uncertain", "summary": "s", "analysis": "a", "priority": "medium"}\n```'
        parsed = analysis.parse_and_validate(raw)
        self.assertEqual(parsed["verdict"], "uncertain")

    def test_no_timestamp_is_requested_from_the_model(self):
        prompt = analysis.build_prompt("Set", "@@ -1 +1 @@\n-a\n+b")
        self.assertNotIn("date_time", prompt)
        self.assertIn("Do not include a timestamp", prompt)


class ConfigIsValidated(unittest.TestCase):
    def test_the_shipped_config_loads(self):
        cfg = load_cfg()
        self.assertTrue(cfg.model)
        self.assertGreater(cfg.validation.min_length, 0)

    def test_out_of_range_value_fails_fast_and_names_the_key(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write("validation:\n  shrink_ratio: 1.5\n")
            path = handle.name
        self.addCleanup(os.unlink, path)
        with self.assertRaises(config.ConfigError) as caught:
            config.load_config(path)
        self.assertIn("shrink_ratio", str(caught.exception))

    def test_unknown_key_is_rejected(self):
        with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False, encoding="utf-8") as handle:
            handle.write("validaton:\n  min_length: 500\n")
            path = handle.name
        self.addCleanup(os.unlink, path)
        with self.assertRaises(config.ConfigError) as caught:
            config.load_config(path)
        self.assertIn("validaton", str(caught.exception))

    def test_per_source_noise_is_reachable_by_host(self):
        cfg = load_cfg()
        patterns = cfg.noise_patterns_for("www.perplexity.ai")
        self.assertTrue(any("privacy notice" in p.lower() for p in patterns))


class LegacyAggregatesSplitCleanly(unittest.TestCase):
    def test_round_trip(self):
        sections = [("https://a.example/terms", "Alpha"), ("https://b.example/privacy", "Beta")]
        aggregate = content.build_aggregate(sections)
        self.assertEqual(content.split_aggregate(aggregate), dict(sections))

    def test_real_archive_splits_into_its_three_urls(self):
        sections = content.split_aggregate(read_fixture(PERPLEXITY_8_AUG))
        self.assertEqual(len(sections), 3)


class UnsafeUrlsAreRefused(unittest.TestCase):
    def test_scheme_validation(self):
        self.assertTrue(fetching.is_safe_url("https://example.gov.au/policy"))
        self.assertTrue(fetching.is_safe_url("http://example.gov.au/policy"))
        for bad in ("file:///etc/passwd", "javascript:alert(1)", "not a url", ""):
            self.assertFalse(fetching.is_safe_url(bad), bad)


class HealthMakesBrokenSourcesVisible(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()

    def test_a_source_failing_three_runs_is_reported_and_alerted(self):
        hashes = {
            "Broken Source": {
                "file_id": "Broken_Source",
                "last_success": "2026-02-01T00:00:00+10:00",
                "consecutive_failures": 3,
                "documents": {
                    "https://example.gov.au/policy": {
                        "label": "Policy",
                        "consecutive_failures": 3,
                        "last_success": "2026-02-01T00:00:00+10:00",
                        "last_error": "block_page: matched failure signature",
                    }
                },
            }
        }
        report = health.build_report(hashes, self.cfg)
        self.assertEqual(report["overall"], health.FAILING)
        self.assertEqual(report["sources"]["Broken Source"]["status"], health.FAILING)
        self.assertEqual(len(report["alerts"]), 1)
        self.assertIn("Broken Source", first_alert_body(report))

    def test_a_healthy_source_raises_nothing(self):
        hashes = {
            "Fine": {
                "file_id": "Fine",
                "last_success": "2026-08-13T00:00:00+10:00",
                "consecutive_failures": 0,
                "documents": {"https://example.gov.au/p": {"consecutive_failures": 0}},
            }
        }
        report = health.build_report(hashes, self.cfg)
        self.assertEqual(report["overall"], health.OK)
        self.assertEqual(report["alerts"], [])
        self.assertEqual(first_alert_body(report), "")


class HistoryIndexesTheArchive(unittest.TestCase):
    def test_it_parses_the_real_log_directory(self):
        index = history.build_index(os.path.join(REPO_ROOT, "logs"))
        self.assertIn("Perplexity_AI_Legal_Policies", index["entries"])
        records = index["entries"]["Perplexity_AI_Legal_Policies"]
        self.assertGreater(len(records), 50)
        self.assertGreater(records[0]["timestamp"], records[-1]["timestamp"])
        self.assertIn("analysis_path", records[0])

    def test_unknown_file_ids_are_excluded(self):
        index = history.build_index(os.path.join(REPO_ROOT, "logs"), known_file_ids={"Google_AI_Policies"})
        self.assertEqual(set(index["entries"]), {"Google_AI_Policies"})


class DocumentLabelsAreReadable(unittest.TestCase):
    def test_labels_derive_from_the_url_path(self):
        self.assertEqual(content.document_label({"url": "https://www.anthropic.com/legal/aup"}), "Aup")
        self.assertEqual(
            content.document_label({"url": "https://www.perplexity.ai/hub/legal/terms-of-service"}),
            "Terms Of Service",
        )

    def test_an_explicit_label_wins(self):
        self.assertEqual(
            content.document_label(
                {"url": "https://www.anthropic.com/legal/aup", "label": "Acceptable Use Policy"}
            ),
            "Acceptable Use Policy",
        )

    def test_document_ids_are_stable_and_distinct(self):
        a = content.document_id("https://www.anthropic.com/legal/aup")
        b = content.document_id("https://www.anthropic.com/legal/privacy")
        self.assertEqual(a, content.document_id("https://www.anthropic.com/legal/aup"))
        self.assertNotEqual(a, b)


class DiffsCarryFingerprints(unittest.TestCase):
    def test_watchlist_terms_are_tagged_from_changed_lines_only(self):
        old = "Disputes are resolved in court.\nWe retain data for 30 days."
        new = "Disputes are resolved by binding arbitration.\nWe retain data for 30 days."
        result = diffing.compute_diff(old, new, watchlist=["arbitration", "indemnify"])
        self.assertIn("watchlist:arbitration", result.tags)
        self.assertNotIn("watchlist:indemnify", result.tags)

    def test_unchanged_context_lines_do_not_raise_tags(self):
        old = "We may indemnify nobody.\nFees are $5."
        new = "We may indemnify nobody.\nFees are $5.\nA new sentence about nothing."
        result = diffing.compute_diff(old, new, context_lines=3, watchlist=["indemnify"])
        self.assertNotIn("watchlist:indemnify", result.tags)
        self.assertNotIn("money", result.tags)

    def test_identical_text_produces_an_empty_diff(self):
        result = diffing.compute_diff("same\ntext", "same\ntext")
        self.assertTrue(result.is_empty)
        self.assertEqual(result.text, "")


if __name__ == "__main__":
    unittest.main()


class AlertsFireOnTransitionsNotStates(unittest.TestCase):
    """One comment per run for as long as a source stayed broken is how
    digital.gov.au produced thirty-five identical tables and was then ignored
    for a month. An alert has to say what changed."""

    def setUp(self):
        self.cfg = load_cfg()
        self.report = health.build_report(
            {
                "Broken Source": {
                    "file_id": "Broken_Source",
                    "last_success": "2026-02-01T00:00:00+10:00",
                    "consecutive_failures": 3,
                    "documents": {
                        "https://example.gov.au/policy": {
                            "label": "Policy",
                            "consecutive_failures": 3,
                            "last_success": "2026-02-01T00:00:00+10:00",
                            "last_error": "block_page: matched failure signature",
                        }
                    },
                }
            },
            self.cfg,
        )
        self.empty = {"open": {}, "last_digest_at": None}

    def test_a_newly_failing_source_is_reported(self):
        delta = health.diff_alerts(self.empty, self.report)
        self.assertEqual(len(delta.new), 1)
        self.assertEqual(delta.ongoing, [])
        self.assertTrue(delta.worth_reporting)
        self.assertIn("started failing", health.render_alert_markdown(delta, self.report))

    def test_the_same_failure_tomorrow_is_not_reported_again(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        state = {
            "open": {
                health.alert_key(self.report["alerts"][0]): {
                    **self.report["alerts"][0],
                    "first_seen": now.isoformat(),
                }
            },
            "last_digest_at": now.isoformat(),
        }
        delta = health.diff_alerts(
            state, self.report, now=now + timedelta(days=1), digest_days=7
        )
        self.assertEqual(delta.new, [])
        self.assertEqual(len(delta.ongoing), 1)
        self.assertFalse(delta.worth_reporting)
        self.assertEqual(health.render_alert_markdown(delta, self.report), "")

    def test_a_failure_still_open_a_week_later_is_digested(self):
        now = datetime(2026, 9, 1, tzinfo=timezone.utc)
        state = {
            "open": {
                health.alert_key(self.report["alerts"][0]): {
                    **self.report["alerts"][0],
                    "first_seen": now.isoformat(),
                }
            },
            "last_digest_at": now.isoformat(),
        }
        delta = health.diff_alerts(
            state, self.report, now=now + timedelta(days=8), digest_days=7
        )
        self.assertTrue(delta.digest_due)
        self.assertTrue(delta.worth_reporting)
        self.assertIn("Still open", health.render_alert_markdown(delta, self.report))

    def test_recovery_is_reported(self):
        state = {
            "open": {
                health.alert_key(self.report["alerts"][0]): self.report["alerts"][0]
            },
            "last_digest_at": None,
        }
        healthy = health.build_report(
            {
                "Broken Source": {
                    "file_id": "Broken_Source",
                    "last_success": "2026-09-16T00:00:00+10:00",
                    "consecutive_failures": 0,
                    "documents": {
                        "https://example.gov.au/policy": {"consecutive_failures": 0}
                    },
                }
            },
            self.cfg,
        )
        delta = health.diff_alerts(state, healthy)
        self.assertEqual(len(delta.recovered), 1)
        self.assertIn("recovered", health.render_alert_markdown(delta, healthy))

    def test_the_failure_count_changing_is_not_a_new_alert(self):
        """A source that fails again tomorrow is the same alert, not a new one."""
        first = self.report["alerts"][0]
        worse = {**first, "consecutive_failures": 12, "detail": "a different message"}
        self.assertEqual(health.alert_key(first), health.alert_key(worse))


class ADisabledSourceIsNotAFailingSource(unittest.TestCase):
    """A source nobody is checking and a source that cannot be checked look
    identical on a dashboard that only reports the last reading, and they call
    for completely different responses."""

    def setUp(self):
        self.cfg = load_cfg()
        self.hashes = {
            "Blocked By A WAF": {
                "file_id": "Blocked_By_A_WAF",
                "monitoring": "disabled",
                "disabled_reason": "Bot protection; needs a residential proxy.",
                "disabled_since": "2026-09-16T00:00:00+10:00",
                "consecutive_failures": 35,
                "documents": {
                    "https://example.gov.au/p": {
                        "consecutive_failures": 35,
                        "last_error": "too_short",
                    }
                },
            }
        }

    def test_it_raises_no_alert(self):
        report = health.build_report(self.hashes, self.cfg)
        self.assertEqual(report["alerts"], [])

    def test_it_does_not_drag_down_the_overall_status(self):
        report = health.build_report(self.hashes, self.cfg)
        self.assertEqual(report["overall"], health.OK)

    def test_it_is_still_reported_with_its_reason(self):
        report = health.build_report(self.hashes, self.cfg)
        source = report["sources"]["Blocked By A WAF"]
        self.assertEqual(source["status"], health.DISABLED)
        self.assertIn("residential proxy", source["disabled_reason"])

    def test_it_is_excluded_from_the_monitored_count(self):
        report = health.build_report(self.hashes, self.cfg)
        self.assertEqual(report["monitored_sources"], 0)


class ASourceCanBeDisabledWithoutBeingDeleted(unittest.TestCase):
    """Deleting a set orphans its snapshots, diffs and a year of archived
    analyses. Disabling it keeps the record and stops the pretence that its
    last reading is current."""

    def test_a_set_is_monitored_unless_it_says_otherwise(self):
        self.assertTrue(main.is_enabled({"setName": "X"}))
        self.assertTrue(main.is_enabled({"setName": "X", "enabled": True}))
        self.assertFalse(main.is_enabled({"setName": "X", "enabled": False}))

    def test_a_non_boolean_enabled_is_rejected(self):
        sets = [
            {
                "setName": "Sloppy",
                "category": "Test",
                "enabled": "false",
                "urls": [{"url": "https://example.gov.au/p"}],
            }
        ]
        self.assertEqual(main.validate_policy_sets(sets), [])

    def test_disabling_carries_the_stored_state_forward(self):
        previous = {
            "hash": "abc",
            "last_amended": "2026-03-17T00:00:00+10:00",
            "last_priority": "medium",
            "documents": {"https://example.gov.au/p": {"hash": "abc"}},
        }
        entry = main.disabled_entry(
            {
                "setName": "Blocked",
                "category": "Test",
                "enabled": False,
                "disabled_reason": "Bot protection.",
                "urls": [{"url": "https://example.gov.au/p"}],
            },
            previous,
            "2026-09-16T00:00:00+10:00",
        )
        self.assertEqual(entry["monitoring"], "disabled")
        self.assertEqual(entry["disabled_reason"], "Bot protection.")
        self.assertEqual(entry["disabled_since"], "2026-09-16T00:00:00+10:00")
        # The archive still has to resolve, so nothing stored is thrown away.
        self.assertEqual(entry["last_amended"], "2026-03-17T00:00:00+10:00")
        self.assertEqual(entry["documents"], previous["documents"])

    def test_a_missing_reason_is_recorded_as_missing_not_omitted(self):
        entry = main.disabled_entry(
            {"setName": "Blocked", "category": "Test", "enabled": False, "urls": []},
            {},
            "2026-09-16T00:00:00+10:00",
        )
        self.assertEqual(entry["disabled_reason"], "No reason recorded.")

    def test_disabled_since_is_not_reset_on_every_run(self):
        first = main.disabled_entry(
            {"setName": "B", "category": "T", "enabled": False, "urls": []},
            {},
            "2026-09-01T00:00:00+10:00",
        )
        second = main.disabled_entry(
            {"setName": "B", "category": "T", "enabled": False, "urls": []},
            first,
            "2026-09-16T00:00:00+10:00",
        )
        self.assertEqual(second["disabled_since"], "2026-09-01T00:00:00+10:00")
