"""Regression tests for the false changes that still reached the model after
the August 2026 upgrade.

Between 13 August and 24 September 2026 the pipeline made eleven model calls.
Two were genuine amendments. Six came back `no_material_change` and three
were recorded as schema failures. Each class below pins one of the causes,
using the text from the runs that produced them:

* Google's AI Principles page alternating between an em dash and a stray 'â'
  (a charset fallback), then between 'lifecycle—from' and 'lifecycle — from';
* an NSW page gaining 'https://' in front of a link it already had;
* digital.gov.au stuck behind a stored baseline that was itself a Chrome
  error page, and a web-application-firewall page nobody recognised;
* a 503 from an overloaded model spent as the one schema retry.
"""

from __future__ import annotations

import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import main
from steward import PIPELINE_VERSION, analysis as llm, config, content, diffing, fetching, runlog
from steward.validation import BLOCK_PAGE, validate_capture

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# From logs/Google_AI_Policies_20260924_141720_diff.txt, as the page reads
# once it is decoded correctly.
GOOGLE_STORED = (
    "Guided by our AI Principles, our AI governance is operationalized through a "
    "comprehensive and multi-layered approach that spans the entire model lifecycle—from "
    "responsible model development and deployment to post-launch monitoring and remediation."
)
GOOGLE_CURRENT = GOOGLE_STORED.replace("lifecycle—from", "lifecycle — from")

# The 256-character page digital.gov.au serves to datacentre addresses.
WAF_PAGE = (
    "Your request has been blocked. Here are some possible reasons why your "
    "information cannot be processed, and some tips on how to solve the issue: "
    "A high volume of simultaneous submissions from your network have been made "
    "to this website. Reference Number: 18.ed263e17.1790267377.874016cb"
)

CHROME_ERROR = (
    "This site can’t be reached\nThe webpage at\n"
    "https://www.digital.gov.au/policy/ai/implementation\n"
    "might be temporarily down or it may have moved permanently to a new web address.\n"
    "ERR_NO_SUPPORTED_PROXIES"
)

URL = "https://example.gov.au/policy"
FILLER = "\n".join(f"Clause {n}. The agency will keep records of decision {n}." for n in range(1, 40))


def load_cfg():
    return config.load_config(os.path.join(REPO_ROOT, "steward_config.yaml"))


class _Response:
    def __init__(self, body: bytes, content_type: str):
        self.content = body
        self.headers = {"Content-Type": content_type}
        # What requests does when a text/* response declares no charset.
        declared = content_type.lower().split("charset=")[-1] if "charset=" in content_type.lower() else None
        self.encoding = declared or "ISO-8859-1"
        self.apparent_encoding = "windows-1252"

    @property
    def text(self) -> str:
        return self.content.decode(self.encoding, errors="replace")


class UndeclaredCharsetIsNotMisread(unittest.TestCase):
    def test_utf8_without_a_declared_charset_keeps_its_em_dash(self):
        response = _Response("lifecycle—from".encode("utf-8"), "text/html")
        self.assertIn("â", response.text, "the fixture must reproduce requests' fallback")
        self.assertEqual(fetching.decode_body(response), "lifecycle—from")

    def test_a_declared_charset_is_honoured(self):
        response = _Response("café".encode("latin-1"), "text/html; charset=ISO-8859-1")
        self.assertEqual(fetching.decode_body(response), "café")

    def test_bytes_that_are_not_utf8_fall_back_to_detection(self):
        response = _Response("naïve “quote”".encode("windows-1252"), "text/html")
        self.assertEqual(fetching.decode_body(response), "naïve “quote”")

    def test_the_fix_is_accompanied_by_a_pipeline_version_bump(self):
        # Stored text decoded under the old rule is incomparable with new
        # captures; the bump re-baselines it rather than reporting a change.
        self.assertGreaterEqual(PIPELINE_VERSION, 3)


class TypographyIsNotAChange(unittest.TestCase):
    def test_spacing_around_an_em_dash_is_cosmetic(self):
        self.assertTrue(diffing.is_cosmetic(GOOGLE_STORED, GOOGLE_CURRENT))

    def test_a_link_gaining_its_scheme_is_cosmetic(self):
        # logs/NSW_Government_AI_Guidance_20260914_142808_diff.txt
        self.assertTrue(
            diffing.is_cosmetic("Website: www.afca.org.au", "Website: https://www.afca.org.au/")
        )

    def test_quotes_case_and_rewrapping_are_cosmetic(self):
        stored = "You “may not” resell\nthe Service."
        current = 'You "May Not" resell the service.'
        self.assertTrue(diffing.is_cosmetic(stored, current))

    def test_a_changed_word_is_not_cosmetic(self):
        self.assertFalse(diffing.is_cosmetic("You may not resell", "You may resell"))
        self.assertFalse(diffing.is_cosmetic("Fees are $10.", "Fees are $100."))
        self.assertFalse(diffing.is_cosmetic("www.afca.org.au", "www.afca.com.au"))

    def test_a_retyped_document_produces_an_empty_diff(self):
        result = diffing.compute_diff(GOOGLE_STORED, GOOGLE_CURRENT, label="Principles")
        self.assertTrue(result.is_empty)
        self.assertGreater(result.cosmetic_lines, 0)

    def test_a_real_edit_next_to_a_rewrapped_paragraph_is_isolated(self):
        stored = f"Intro.\n{GOOGLE_STORED}\nClause 2. Fees are billed monthly.\nClause 3. End."
        current = (
            f"Intro.\n{GOOGLE_CURRENT.replace(' responsible', chr(10) + 'responsible')}\n"
            "Clause 2. Fees are billed weekly.\nClause 3. End."
        )
        result = diffing.compute_diff(stored, current, label="Terms")
        self.assertEqual((result.added, result.removed), (1, 1))
        self.assertIn("+Clause 2. Fees are billed weekly.", result.text)
        self.assertNotIn("lifecycle — from", result.text, "the cosmetic line must not reach the model")


class _DocumentHarness(unittest.TestCase):
    def setUp(self):
        self.cfg = load_cfg()
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        cwd = os.getcwd()
        os.chdir(self.tmp.name)
        self.addCleanup(os.chdir, cwd)
        main.setup_directories()

        self.capture = ""
        original = fetching.fetch_document
        fetching.fetch_document = lambda url_data, prior, cfg, policy_set=None, session=None: fetching.FetchResult(
            url_data["url"], fetching.OK, text=self.capture, extractor=fetching.EXTRACTOR_TRAFILATURA
        )
        self.addCleanup(setattr, fetching, "fetch_document", original)

        self.file_id = "Fixture_Set"
        self.doc_id = content.document_id(URL)

    def seed(self, text: str, **extra) -> dict:
        normalised = content.normalise(text)
        main.write_text(main.document_snapshot_path(self.file_id, self.doc_id), normalised)
        prior = {
            "doc_id": self.doc_id,
            "hash": content.content_hash(normalised),
            "length": len(normalised),
            "pipeline_version": PIPELINE_VERSION,
            "consecutive_failures": 0,
        }
        prior.update(extra)
        return prior

    def process(self, prior: dict, capture: str):
        self.capture = capture
        record, outcome, diff, text = main.process_document(
            {"url": URL}, {}, self.file_id, prior, self.cfg, "2026-09-24T14:17:20+10:00"
        )
        if outcome in main._BASELINE_OUTCOMES:
            main.write_text(main.document_snapshot_path(self.file_id, self.doc_id), text)
        return record, outcome, diff


class CosmeticChangesStopBeforeTheModel(_DocumentHarness):
    def test_the_24_september_google_diff_is_recorded_as_cosmetic(self):
        prior = self.seed(f"{FILLER}\n{GOOGLE_STORED}")
        record, outcome, diff = self.process(prior, f"{FILLER}\n{GOOGLE_CURRENT}")
        self.assertEqual(outcome, main.DOC_COSMETIC)
        self.assertIsNone(diff)
        self.assertGreater(record["cosmetic_lines"], 0)

    def test_the_cosmetic_text_becomes_the_baseline(self):
        prior = self.seed(f"{FILLER}\n{GOOGLE_STORED}")
        record, _, _ = self.process(prior, f"{FILLER}\n{GOOGLE_CURRENT}")
        again, outcome, _ = self.process(record, f"{FILLER}\n{GOOGLE_CURRENT}")
        self.assertEqual(outcome, main.DOC_UNCHANGED)


class FlipFlopsAreRecordedNotReanalysed(_DocumentHarness):
    def test_returning_to_a_seen_version_is_a_revert(self):
        version_a = f"{FILLER}\nFees are billed monthly."
        version_b = f"{FILLER}\nFees are billed weekly."

        prior = self.seed(version_a)
        record, outcome, diff = self.process(prior, version_b)
        self.assertEqual(outcome, main.DOC_CHANGED)
        self.assertIsNotNone(diff)

        record, outcome, diff = self.process(record, version_a)
        self.assertEqual(outcome, main.DOC_REVERTED)
        self.assertIsNone(diff, "a revert must not be analysed again")

        record, outcome, diff = self.process(record, version_b)
        self.assertEqual(outcome, main.DOC_REVERTED, "the flip back is a revert too")

    def test_memory_is_bounded(self):
        prior = self.seed(f"{FILLER}\nv0")
        for n in range(1, 10):
            prior, _, _ = self.process(prior, f"{FILLER}\nv{n}")
        self.assertLessEqual(len(prior["previous_hashes"]), self.cfg.diff.revert_memory)

    def test_a_set_level_revert_is_explained_not_badged(self):
        policy_set = {"setName": "Fixture Set", "category": "Test", "urls": [{"url": URL}]}
        version_a = f"{FILLER}\nFees are billed monthly."
        version_b = f"{FILLER}\nFees are billed weekly."
        prior_doc = self.seed(version_a, previous_hashes=[content.content_hash(content.normalise(version_b))])
        previous = {
            "hash": "x",
            "file_id": self.file_id,
            "last_amended": "2026-09-01T00:00:00+10:00",
            "last_priority": "high",
            "documents": {URL: prior_doc},
        }
        calls = []
        original = llm.analyse_change
        llm.analyse_change = lambda *a, **k: calls.append(a) or llm.AnalysisOutcome()
        self.addCleanup(setattr, llm, "analyse_change", original)

        self.capture = version_b
        entry = main.process_policy_set(policy_set, previous, self.cfg, runlog.RunLog("t"), False)
        self.assertEqual(calls, [])
        self.assertEqual(entry["last_amended"], previous["last_amended"])
        self.assertEqual(entry["last_review"]["verdict"], "reverted")


class APoisonedBaselineCanRecover(_DocumentHarness):
    def test_a_stored_error_page_is_replaced_by_the_first_real_capture(self):
        # hashes.json held length 347 for each digital.gov.au page: the real
        # page would have been rejected as growing 50-fold, forever.
        prior = self.seed(CHROME_ERROR)
        record, outcome, diff = self.process(prior, FILLER)
        self.assertEqual(outcome, main.DOC_REBASELINED)
        self.assertEqual(record["rebaseline_reason"], "stored baseline was not a valid capture")
        self.assertIsNone(diff)

    def test_the_firewall_page_is_named_as_a_block(self):
        cfg = load_cfg()
        verdict = validate_capture(
            WAF_PAGE,
            None,
            min_length=cfg.validation.min_length,
            shrink_ratio=cfg.validation.shrink_ratio,
            growth_ratio=cfg.validation.growth_ratio,
            failure_signatures=cfg.validation.failure_signatures,
        )
        self.assertEqual(verdict.reason, BLOCK_PAGE)


class _FakeModels:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def generate_content(self, model, contents, config):
        self.calls.append(config)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


class _FakeClient:
    def __init__(self, script):
        self.models = _FakeModels(script)


class _Overloaded(Exception):
    code = 503


class _Reply:
    def __init__(self, text):
        self.text = text
        self.usage_metadata = None


GOOD = '{"verdict": "material_change", "summary": "s", "analysis": "a", "priority": "high"}'


class AnOverloadedModelIsWaitedOut(unittest.TestCase):
    def test_a_503_is_retried_after_a_pause_not_spent_as_the_schema_retry(self):
        waits = []
        client = _FakeClient([_Overloaded("503 UNAVAILABLE"), _Reply(GOOD)])
        outcome = llm.analyse_change("Set", "diff", model="m", client=client, sleep=waits.append)
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.attempts, 1)
        self.assertEqual(len(waits), 1)

    def test_persistent_overload_is_reported_as_unavailable(self):
        client = _FakeClient([_Overloaded("503 UNAVAILABLE")] * 10)
        outcome = llm.analyse_change("Set", "diff", model="m", client=client, sleep=lambda _: None)
        self.assertFalse(outcome.ok)
        self.assertTrue(outcome.unavailable)

    def test_the_schema_is_enforced_by_the_api_as_well_as_checked(self):
        client = _FakeClient([_Reply(GOOD)])
        llm.analyse_change("Set", "diff", model="m", client=client, sleep=lambda _: None)
        schema = client.models.calls[0].response_schema
        self.assertEqual(schema["properties"]["priority"]["enum"], list(llm.PRIORITIES))
        self.assertIn("verdict", schema["required"])


class AnUnavailableModelIsNotASchemaFailure(_DocumentHarness):
    def test_the_change_is_kept_for_next_run_without_raising_the_schema_alert(self):
        policy_set = {"setName": "Fixture Set", "category": "Test", "urls": [{"url": URL}]}
        prior_doc = self.seed(f"{FILLER}\nFees are billed monthly.")
        previous = {"hash": "x", "file_id": self.file_id, "schema_failures": 0, "documents": {URL: prior_doc}}
        original = llm.analyse_change
        llm.analyse_change = lambda *a, **k: llm.AnalysisOutcome(error="503", attempts=1, unavailable=True)
        self.addCleanup(setattr, llm, "analyse_change", original)

        self.capture = f"{FILLER}\nFees are billed weekly."
        log = runlog.RunLog("t")
        entry = main.process_policy_set(policy_set, previous, self.cfg, log, False)
        self.assertEqual(entry["schema_failures"], 0)
        self.assertEqual(entry["documents"][URL]["hash"], prior_doc["hash"])
        self.assertIn("api_unavailable", log.counts_by_outcome())


class ActivityShowsTheFilteringAtWork(unittest.TestCase):
    def test_each_outcome_lands_in_its_bucket(self):
        records = [
            {"run_id": "r1", "set_name": "S", "outcome": "unchanged"},
            {"run_id": "r1", "set_name": "S", "outcome": "cosmetic"},
            {"run_id": "r2", "set_name": "S", "outcome": "reverted"},
            {"run_id": "r2", "set_name": "S", "outcome": "suspect_scrape"},
            {"run_id": "r2", "set_name": "S", "outcome": "changed"},
            {"run_id": "r2", "set_name": "S", "outcome": "analysed", "llm_called": True,
             "verdict": "no_material_change"},
        ]
        counts = runlog.activity_summary(records)["S"]
        self.assertEqual(counts["runs"], 2)
        self.assertEqual(counts["checks"], 5)
        self.assertEqual(counts["filtered"], 2)
        self.assertEqual(counts["rejected"], 1)
        self.assertEqual((counts["analysed"], counts["declined"], counts["material"]), (1, 1, 0))

    def test_each_day_is_counted_on_its_own(self):
        records = [
            {"run_id": "r1", "set_name": "S", "timestamp": "2026-09-23T10:00:00+10:00", "outcome": "unchanged"},
            {"run_id": "r1", "set_name": "S", "timestamp": "2026-09-23T10:00:00+10:00", "outcome": "suspect_scrape"},
            {"run_id": "r2", "set_name": "S", "timestamp": "2026-09-24T10:00:00+10:00", "outcome": "changed"},
            {"run_id": "r2", "set_name": "S", "timestamp": "2026-09-24T10:00:00+10:00", "outcome": "analysed",
             "llm_called": True, "verdict": "material_change"},
            {"run_id": "r2", "set_name": "T", "timestamp": "2026-09-24T10:00:00+10:00", "outcome": "fetch_failed"},
            {"run_id": "r2", "set_name": "T", "outcome": "unchanged"},
        ]
        daily = runlog.daily_summary(records)
        self.assertEqual(
            daily["S"],
            [
                {"date": "2026-09-23", "checks": 2, "unchanged": 1, "rejected": 1},
                {"date": "2026-09-24", "checks": 1, "changed": 1, "analysed": 1, "material": 1},
            ],
        )
        # An undated record cannot be placed on a day, so it is left out.
        self.assertEqual(daily["T"], [{"date": "2026-09-24", "checks": 1, "failed": 1}])


if __name__ == "__main__":
    unittest.main()
