"""End-to-end replays of the runs that put false alerts on the dashboard.

The unit tests pin each gate. These drive a whole policy set through
`process_policy_set` with the network and the model stubbed, and assert on the
thing the steward actually sees: whether the set gets badged, whether
`last_amended` moves, and whether a model call happens at all.

The 7, 8 and 9 August 2026 Perplexity runs are replayed from the archives in
logs/ — the same files that produced the two false criticals.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from steward import PIPELINE_VERSION, analysis as llm, content, fetching, health, runlog

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOGS = os.path.join(REPO_ROOT, "logs")

TOS = "https://www.perplexity.ai/hub/legal/terms-of-service"
PRIVACY = "https://www.perplexity.ai/hub/legal/privacy-policy"
AUP = "https://www.perplexity.ai/hub/legal/aup"

PERPLEXITY_SET = {
    "setName": "Perplexity AI Legal Policies",
    "category": "Private Sector",
    "urls": [{"url": TOS}, {"url": PRIVACY}, {"url": AUP}],
}
FILE_ID = "Perplexity_AI_Legal_Policies"


def archived(day: str) -> dict:
    """Per-URL text from an archived aggregate snapshot."""
    name = {
        "7aug": "Perplexity_AI_Legal_Policies_20260807_125653_snapshot.txt",
        "8aug": "Perplexity_AI_Legal_Policies_20260808_120221_snapshot.txt",
    }[day]
    with open(os.path.join(LOGS, name), encoding="utf-8") as handle:
        return content.split_aggregate(handle.read())


def load_cfg():
    from steward import config

    return config.load_config(os.path.join(REPO_ROOT, "steward_config.yaml"))


class RunHarness(unittest.TestCase):
    """Runs process_policy_set in a scratch directory with the network and the
    model replaced by fixtures."""

    def setUp(self):
        self.cfg = load_cfg()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        main.setup_directories()

        self.llm_calls = []
        self.responses = {}

        original_fetch = fetching.fetch_document
        original_analyse = llm.analyse_change
        self.addCleanup(setattr, fetching, "fetch_document", original_fetch)
        self.addCleanup(setattr, llm, "analyse_change", original_analyse)

        fetching.fetch_document = self._fetch
        llm.analyse_change = self._analyse

    # --- Stubs ---

    def _fetch(self, url_data, prior, cfg, policy_set=None):
        url = url_data["url"]
        if url not in self.responses:
            return fetching.FetchResult(url, fetching.FAILED, error="no fixture registered")
        text = self.responses[url]
        if text is None:
            return fetching.FetchResult(url, fetching.NOT_MODIFIED, http_status=304)
        return fetching.FetchResult(
            url, fetching.OK, text=text, extractor=fetching.EXTRACTOR_TRAFILATURA
        )

    def _analyse(self, set_name, diff_text, *, model, changed_documents=(), tags=(), client=None):
        self.llm_calls.append(
            {
                "set_name": set_name,
                "diff": diff_text,
                "changed_documents": list(changed_documents),
                "tags": list(tags),
            }
        )
        return llm.AnalysisOutcome(
            result=self.verdict, attempts=1, prompt_tokens=900, output_tokens=250
        )

    verdict = {
        "verdict": "material_change",
        "summary": "Something material changed.",
        "analysis": "## Detail\n\nA clause moved.",
        "priority": "high",
    }

    # --- Helpers ---

    def normalised(self, url: str, sections: dict) -> str:
        """Normalise exactly as the pipeline does, per-source noise included."""
        return content.normalise(
            sections[url], self.cfg.noise_patterns_for(content.host_of(url))
        )

    def seed_from(self, sections: dict) -> dict:
        """Build a hashes.json entry and the per-document snapshots for a day."""
        documents = {}
        for url in (TOS, PRIVACY, AUP):
            text = self.normalised(url, sections)
            doc_id = content.document_id(url)
            main.write_text(main.document_snapshot_path(FILE_ID, doc_id), text)
            documents[url] = {
                "doc_id": doc_id,
                "label": content.document_label({"url": url}),
                "hash": content.content_hash(text),
                "length": len(text),
                "pipeline_version": PIPELINE_VERSION,
                "consecutive_failures": 0,
                "last_success": "2026-08-07T12:56:53+10:00",
                "status": main.DOC_UNCHANGED,
            }
        main._write_aggregate(
            FILE_ID, [(url, self.normalised(url, sections)) for url in (TOS, PRIVACY, AUP)]
        )
        return {
            "hash": main.rollup_hash([documents[u]["hash"] for u in sorted(documents)]),
            "category": "Private Sector",
            "urls": PERPLEXITY_SET["urls"],
            "file_id": FILE_ID,
            "last_checked": "2026-08-07T12:56:53+10:00",
            "last_amended": "2026-07-15T00:00:00+10:00",
            "last_priority": "medium",
            "consecutive_failures": 0,
            "last_success": "2026-08-07T12:56:53+10:00",
            "documents": documents,
        }

    def run_set(self, previous, dry_run=False):
        log = runlog.RunLog("test")
        entry = main.process_policy_set(PERPLEXITY_SET, previous, self.cfg, log, dry_run)
        return entry, log


class TheEighthOfAugustProducesNoAlert(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.eighth = archived("8aug")
        self.previous = self.seed_from(self.seventh)
        self.responses = {
            TOS: self.eighth[TOS],        # 354 bytes of Chrome error page
            PRIVACY: self.eighth[PRIVACY],  # byte-identical to the 7th
            AUP: self.eighth[AUP],          # byte-identical to the 7th
        }

    def test_no_model_call_is_made(self):
        _, log = self.run_set(self.previous)
        self.assertEqual(
            self.llm_calls, [], "the block page must not reach the model at any priority"
        )
        self.assertEqual(log.token_totals()["llm_calls"], 0)

    def test_the_set_is_not_badged_and_last_amended_does_not_move(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(entry["last_amended"], self.previous["last_amended"])
        self.assertEqual(entry["last_priority"], "medium")

    def test_the_bad_capture_does_not_overwrite_the_stored_snapshot(self):
        entry, _ = self.run_set(self.previous)
        doc_id = content.document_id(TOS)
        stored = main.read_text(main.document_snapshot_path(FILE_ID, doc_id))
        self.assertEqual(
            content.content_hash(stored), self.previous["documents"][TOS]["hash"]
        )
        self.assertEqual(entry["documents"][TOS]["hash"], self.previous["documents"][TOS]["hash"])

    def test_the_failure_is_recorded_rather_than_swallowed(self):
        entry, log = self.run_set(self.previous)
        tos = entry["documents"][TOS]
        self.assertEqual(tos["status"], main.DOC_SUSPECT)
        self.assertEqual(tos["consecutive_failures"], 1)
        self.assertIn("block_page", tos["last_error"])
        self.assertEqual(entry["status"], health.DEGRADED)
        self.assertEqual(log.counts_by_outcome()[main.DOC_SUSPECT], 1)

    def test_the_sibling_documents_are_reported_as_unchanged(self):
        entry, _ = self.run_set(self.previous)
        for url in (PRIVACY, AUP):
            self.assertEqual(entry["documents"][url]["status"], main.DOC_UNCHANGED)
            self.assertEqual(entry["documents"][url]["consecutive_failures"], 0)

    def test_the_ninth_of_august_restoration_is_also_a_non_event(self):
        """The second false critical said the Terms of Service had been
        'launched'. With the 8th rejected, the 9th is simply unchanged."""
        entry, _ = self.run_set(self.previous)
        self.responses = {url: self.seventh[url] for url in (TOS, PRIVACY, AUP)}
        restored, _ = self.run_set(entry)

        self.assertEqual(self.llm_calls, [])
        self.assertEqual(restored["documents"][TOS]["status"], main.DOC_UNCHANGED)
        self.assertEqual(restored["last_amended"], self.previous["last_amended"])
        self.assertEqual(restored["status"], health.OK)
        self.assertEqual(restored["consecutive_failures"], 0)

    def test_three_bad_runs_raise_a_health_alert(self):
        entry = self.previous
        for _ in range(3):
            entry, _ = self.run_set(entry)

        self.assertEqual(entry["documents"][TOS]["consecutive_failures"], 3)
        self.assertEqual(entry["status"], health.FAILING)

        report = health.build_report({PERPLEXITY_SET["setName"]: entry}, self.cfg)
        self.assertEqual(report["overall"], health.FAILING)
        self.assertEqual(len(report["alerts"]), 1)
        self.assertIn("Perplexity", health.render_alert_markdown(report))


class AGenuineChangeStillGetsThrough(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.previous = self.seed_from(self.seventh)

        edited = self.seventh[AUP].replace(
            "Acceptable Use Policy",
            "Acceptable Use Policy\n\nDisputes are resolved by binding arbitration in Delaware.",
            1,
        )
        self.responses = {TOS: self.seventh[TOS], PRIVACY: self.seventh[PRIVACY], AUP: edited}

    def test_the_model_is_called_once_with_only_the_changed_document(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(len(self.llm_calls), 1)
        call = self.llm_calls[0]
        self.assertEqual(call["changed_documents"], ["Aup"])
        self.assertIn("arbitration", call["diff"])
        self.assertIn("watchlist:arbitration", call["tags"])
        self.assertEqual(entry["last_change"]["changed_documents"], ["Aup"])

    def test_the_diff_is_far_smaller_than_the_documents(self):
        self.run_set(self.previous)
        diff = self.llm_calls[0]["diff"]
        full = sum(len(self.normalised(u, self.seventh)) for u in (TOS, PRIVACY, AUP))
        self.assertLess(len(diff), full / 10)

    def test_the_set_is_badged_and_the_artefacts_are_written(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(entry["last_priority"], "high")
        self.assertEqual(entry["last_verdict"], "material_change")
        self.assertNotEqual(entry["last_amended"], self.previous["last_amended"])

        self.assertTrue(os.path.exists(main.diff_path(FILE_ID)))
        stored = json.loads(main.read_text(main.analysis_path(FILE_ID)))
        self.assertEqual(stored["changed_documents"], ["Aup"])
        self.assertEqual(stored["date_time"], entry["last_amended"])
        self.assertNotIn("Unknown", stored.values())

    def test_the_timestamp_comes_from_the_code_not_the_model(self):
        entry, _ = self.run_set(self.previous)
        stored = json.loads(main.read_text(main.analysis_path(FILE_ID)))
        # The live Perplexity analysis was stamped 2024-05-16 because the model
        # was asked for the time and invented one.
        self.assertTrue(stored["date_time"].startswith(entry["last_checked"][:4]))
        self.assertEqual(stored["date_time"], entry["last_checked"])

    def test_dry_run_changes_nothing(self):
        entry, _ = self.run_set(self.previous, dry_run=True)
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(entry, self.previous)
        self.assertFalse(os.path.exists(main.diff_path(FILE_ID)))


class TheModelIsAllowedToDecline(RunHarness):
    verdict = {
        "verdict": "no_material_change",
        "summary": "Boilerplate was reordered; nothing of substance moved.",
        "analysis": "The changed lines are navigation text.",
        "priority": "low",
    }

    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.previous = self.seed_from(self.seventh)
        edited = self.seventh[AUP] + "\n\nContact us | Careers | Blog\n"
        self.responses = {TOS: self.seventh[TOS], PRIVACY: self.seventh[PRIVACY], AUP: edited}

    def test_declining_does_not_badge_the_set(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(entry["last_amended"], self.previous["last_amended"])
        self.assertEqual(entry["last_priority"], self.previous["last_priority"])
        self.assertEqual(entry["last_review"]["verdict"], "no_material_change")

    def test_the_new_text_becomes_the_baseline_so_it_is_not_re_analysed(self):
        entry, _ = self.run_set(self.previous)
        self.llm_calls.clear()
        again, _ = self.run_set(entry)
        self.assertEqual(self.llm_calls, [], "the same diff must not be paid for twice")
        self.assertEqual(again["documents"][AUP]["status"], main.DOC_UNCHANGED)

    def test_the_previous_material_analysis_is_not_overwritten(self):
        main.save_json_file(
            {"verdict": "material_change", "summary": "A real change.", "analysis": "x",
             "priority": "critical", "date_time": "2026-07-15T00:00:00+10:00"},
            main.analysis_path(FILE_ID),
        )
        self.run_set(self.previous)
        stored = json.loads(main.read_text(main.analysis_path(FILE_ID)))
        self.assertEqual(stored["summary"], "A real change.")


class SchemaFailureLosesNothing(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.previous = self.seed_from(self.seventh)
        self.responses = {
            TOS: self.seventh[TOS],
            PRIVACY: self.seventh[PRIVACY],
            AUP: self.seventh[AUP] + "\n\nNew clause 9.4 about indemnification.\n",
        }
        llm.analyse_change = lambda *a, **k: llm.AnalysisOutcome(
            result=None, error="priority must be one of critical, high, medium, low, got 'unknown'",
            attempts=2,
        )

    def test_the_change_is_retried_next_run_rather_than_lost(self):
        entry, log = self.run_set(self.previous)
        self.assertEqual(entry["schema_failures"], 1)
        self.assertEqual(entry["last_amended"], self.previous["last_amended"])
        # The stored hash is left at the previous value, so tomorrow's run sees
        # the same change again instead of silently accepting it.
        self.assertEqual(entry["documents"][AUP]["hash"], self.previous["documents"][AUP]["hash"])
        self.assertEqual(log.counts_by_outcome()["schema_failed"], 1)

    def test_no_priority_outside_the_enum_reaches_the_archive(self):
        entry, _ = self.run_set(self.previous)
        self.assertIn(entry["last_priority"], llm.PRIORITIES)


class MigratingFromTheLegacyFormat(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        # A pre-upgrade entry: one MD5 over the whole set, no documents map.
        main._write_aggregate(FILE_ID, [(url, self.seventh[url]) for url in (TOS, PRIVACY, AUP)])
        self.previous = {
            "hash": "30607f34e1d98c0dd991eeee562c3bb4",
            "category": "Private Sector",
            "urls": PERPLEXITY_SET["urls"],
            "file_id": FILE_ID,
            "last_checked": "2026-08-07T12:56:53+10:00",
            "last_amended": "2026-07-15T00:00:00+10:00",
            "last_priority": "critical",
        }
        self.responses = {url: self.seventh[url] for url in (TOS, PRIVACY, AUP)}

    def test_a_changed_extractor_is_re_baselined_not_reported_as_a_change(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(self.llm_calls, [], "a pipeline change is not a policy amendment")
        self.assertEqual(entry["last_amended"], self.previous["last_amended"])
        self.assertEqual(entry["last_priority"], "critical")
        for url in (TOS, PRIVACY, AUP):
            self.assertEqual(entry["documents"][url]["status"], main.DOC_REBASELINED)
            self.assertEqual(entry["documents"][url]["pipeline_version"], PIPELINE_VERSION)

    def test_the_run_after_the_migration_compares_normally(self):
        entry, _ = self.run_set(self.previous)
        self.llm_calls.clear()
        again, _ = self.run_set(entry)
        self.assertEqual(self.llm_calls, [])
        for url in (TOS, PRIVACY, AUP):
            self.assertEqual(again["documents"][url]["status"], main.DOC_UNCHANGED)

    def test_a_real_change_after_migration_is_detected(self):
        entry, _ = self.run_set(self.previous)
        self.responses[AUP] = self.seventh[AUP] + "\n\nWe may indemnify you for up to $500.\n"
        changed, _ = self.run_set(entry)
        self.assertEqual(len(self.llm_calls), 1)
        self.assertEqual(changed["last_change"]["changed_documents"], ["Aup"])


class ProbeShortCircuitsWhenNothingMoved(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.previous = self.seed_from(self.seventh)
        # None means the stub returns 304 Not Modified.
        self.responses = {TOS: None, PRIVACY: None, AUP: None}

    def test_a_304_ends_the_check_for_that_document(self):
        entry, log = self.run_set(self.previous)
        self.assertEqual(self.llm_calls, [])
        for url in (TOS, PRIVACY, AUP):
            self.assertEqual(entry["documents"][url]["status"], main.DOC_NOT_MODIFIED)
        self.assertEqual(log.counts_by_outcome()[main.DOC_NOT_MODIFIED], 3)
        self.assertEqual(entry["status"], health.OK)


class EveryDocumentFailing(RunHarness):
    def setUp(self):
        super().setUp()
        self.seventh = archived("7aug")
        self.previous = self.seed_from(self.seventh)
        self.responses = {}  # every fetch fails

    def test_the_set_is_carried_forward_but_flagged(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(self.llm_calls, [])
        self.assertEqual(entry["last_amended"], self.previous["last_amended"])
        self.assertEqual(entry["consecutive_failures"], 1)
        for url in (TOS, PRIVACY, AUP):
            self.assertEqual(entry["documents"][url]["status"], main.DOC_FETCH_FAILED)

    def test_last_success_stops_advancing(self):
        entry, _ = self.run_set(self.previous)
        self.assertEqual(entry["last_success"], self.previous["last_success"])


if __name__ == "__main__":
    unittest.main()
