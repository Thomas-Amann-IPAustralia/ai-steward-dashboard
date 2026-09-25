"""How documents on hosts that refuse plain HTTP clients are reached.

On 25 September 2026, 31 documents on four gov.au hosts each held a plain
GET open for the full 30-second timeout before Chrome read them in about
five. These pin the fixes: a host that refused once is sent straight to the
browser, one browser serves the whole run, and when no live route works the
Internet Archive's newest capture is used only if it is newer than what is
already held.
"""

from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import main
from steward import fetching
from steward.config import load_config

PAGE = "Policy text that is long enough to be a real document. " * 20


def cfg(**fetch_overrides):
    config = load_config()
    config.fetch.max_retries = 1
    config.fetch.retry_delay_seconds = 0
    for key, value in fetch_overrides.items():
        setattr(config.fetch, key, value)
    return config


class Routes:
    """Stands in for the three routes and records which were used."""

    def __init__(self, plain, render=PAGE):
        self.plain = plain
        self.render = render
        self.calls = []

    def http(self, url_data, prior, cfg, use_proxy):
        self.calls.append(("plain", url_data["url"]))
        if self.plain == "hang":
            return fetching.FetchResult(url_data["url"], fetching.FAILED, error="ReadTimeout: timed out")
        return fetching.FetchResult(
            url_data["url"], fetching.OK, text=self.plain, http_status=200, route=fetching.ROUTE_PLAIN
        )

    def selenium(self, url_data, cfg, use_proxy, session=None):
        self.calls.append(("render", url_data["url"]))
        if self.render is None:
            return fetching.FetchResult(url_data["url"], fetching.FAILED, error="timed out waiting for page body")
        return fetching.FetchResult(
            url_data["url"], fetching.OK, text=self.render, extractor=fetching.EXTRACTOR_SELENIUM, route=fetching.ROUTE_RENDER
        )


class HostMemory(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg(archive_fallback=False)
        patcher = mock.patch.object(fetching, "_proxies", lambda: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _use(self, routes):
        for name, fake in (("_http_fetch", routes.http), ("_selenium_fetch", routes.selenium)):
            patcher = mock.patch.object(fetching, name, fake)
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_only_the_first_document_on_a_refusing_host_waits_for_plain_http(self):
        routes = Routes(plain="hang")
        self._use(routes)
        session = fetching.FetchSession()

        first = fetching.fetch_document({"url": "https://www.digital.gov.au/a"}, {}, self.cfg, session=session)
        second = fetching.fetch_document({"url": "https://www.digital.gov.au/b"}, {}, self.cfg, session=session)
        other = fetching.fetch_document({"url": "https://www.oaic.gov.au/c"}, {}, self.cfg, session=session)

        self.assertTrue(first.ok and second.ok)
        self.assertTrue(first.plain_blocked)
        self.assertIsNone(second.plain_blocked, "plain HTTP was not tried, so nothing new is known")
        self.assertEqual(
            routes.calls,
            [
                ("plain", "https://www.digital.gov.au/a"),
                ("render", "https://www.digital.gov.au/a"),
                ("render", "https://www.digital.gov.au/b"),
                ("plain", "https://www.oaic.gov.au/c"),
                ("render", "https://www.oaic.gov.au/c"),
            ],
        )

    def test_a_host_that_answers_plain_http_is_never_marked(self):
        routes = Routes(plain=PAGE)
        self._use(routes)
        session = fetching.FetchSession()
        result = fetching.fetch_document({"url": "https://www.anthropic.com/legal/aup"}, {}, self.cfg, session=session)
        self.assertIs(result.plain_blocked, False)
        self.assertEqual(session.blocked_hosts, {})

    def test_a_render_that_also_fails_does_not_mark_the_host(self):
        routes = Routes(plain="hang", render=None)
        self._use(routes)
        session = fetching.FetchSession()
        result = fetching.fetch_document({"url": "https://www.digital.gov.au/a"}, {}, self.cfg, session=session)
        self.assertFalse(result.ok)
        self.assertEqual(session.blocked_hosts, {})


class SessionSeeding(unittest.TestCase):
    now = datetime(2026, 9, 25, tzinfo=timezone.utc)

    def test_recent_refusals_are_remembered_and_old_ones_retried(self):
        documents = [
            ("https://www.digital.gov.au/a", {"plain_blocked_at": (self.now - timedelta(days=2)).isoformat()}),
            ("https://www.naa.gov.au/x", {"plain_blocked_at": (self.now - timedelta(days=14)).isoformat()}),
            ("https://www.oaic.gov.au/y", {"plain_blocked_at": None}),
        ]
        session = fetching.FetchSession.remembering(documents, recheck_days=7, now=self.now)
        self.assertTrue(session.is_blocked("https://www.digital.gov.au/other"))
        self.assertFalse(session.is_blocked("https://www.naa.gov.au/x"), "two weeks on, plain HTTP is tried again")
        self.assertFalse(session.is_blocked("https://www.oaic.gov.au/y"))

    def test_hosts_first_refused_together_are_rechecked_on_different_days(self):
        hosts = [f"https://www.agency{i}.gov.au/ai" for i in range(40)]
        first_seen = self.now - timedelta(days=40)
        documents = [(url, {"plain_blocked_at": first_seen.isoformat()}) for url in hosts]
        released_on = []
        for day in range(7, 14):
            later = first_seen + timedelta(days=day, hours=1)
            session = fetching.FetchSession.remembering(documents, recheck_days=7, now=later)
            released_on.append(len(hosts) - len(session.blocked_hosts))
        self.assertEqual(released_on[-1], len(hosts), "every host is re-checked within twice the period")
        self.assertLess(released_on[0], len(hosts) // 2, "but not all on the first day")

    def test_zero_turns_the_memory_off(self):
        documents = [("https://www.digital.gov.au/a", {"plain_blocked_at": self.now.isoformat()})]
        session = fetching.FetchSession.remembering(documents, recheck_days=0, now=self.now)
        self.assertEqual(session.blocked_hosts, {})

    def test_the_stamp_ages_out_rather_than_being_refreshed_by_skipping(self):
        prior = {"plain_blocked_at": "2026-09-20T00:00:00+10:00"}
        skipped = fetching.FetchResult("u", fetching.OK, text=PAGE, route=fetching.ROUTE_RENDER)
        refused = fetching.FetchResult("u", fetching.OK, text=PAGE, route=fetching.ROUTE_RENDER, plain_blocked=True)
        answered = fetching.FetchResult("u", fetching.OK, text=PAGE, route=fetching.ROUTE_PLAIN, plain_blocked=False)
        now = "2026-09-25T00:00:00+10:00"

        self.assertEqual(main.fetch_route_fields(skipped, prior, now)["plain_blocked_at"], prior["plain_blocked_at"])
        self.assertEqual(main.fetch_route_fields(refused, prior, now)["plain_blocked_at"], now)
        self.assertIsNone(main.fetch_route_fields(answered, prior, now)["plain_blocked_at"])


class FakeDriver:
    def __init__(self):
        self.page_source = f"<html><body><article><p>{PAGE}</p></article></body></html>"
        self.quit_calls = 0

    def get(self, url):
        pass

    def find_element(self, *args):
        return object()

    def execute_script(self, *args):
        pass

    def quit(self):
        self.quit_calls += 1


class OneBrowserPerRun(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg()
        self.launched = []

        def launch(cfg, with_proxy=False):
            driver = FakeDriver()
            self.launched.append(driver)
            return driver

        for patcher in (
            mock.patch.object(fetching, "initialize_driver", launch),
            mock.patch.object(fetching.time, "sleep", lambda _: None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)

    def test_a_session_renders_every_page_in_the_same_browser(self):
        session = fetching.FetchSession()
        for path in ("a", "b", "c"):
            result = fetching._selenium_fetch({"url": f"https://www.digital.gov.au/{path}"}, self.cfg, False, session)
            self.assertTrue(result.ok)
        self.assertEqual(len(self.launched), 1)
        self.assertEqual(self.launched[0].quit_calls, 0)
        session.close()
        self.assertEqual(self.launched[0].quit_calls, 1)

    def test_without_a_session_the_browser_is_closed_after_the_page(self):
        fetching._selenium_fetch({"url": "https://www.digital.gov.au/a"}, self.cfg, False)
        self.assertEqual(self.launched[0].quit_calls, 1)


class ArchiveResponse:
    def __init__(self, payload=None, text="", status=200):
        self._payload = payload
        self.status_code = status
        self.headers = {"Content-Type": "text/html; charset=utf-8"}
        self.text = text
        self.content = text.encode("utf-8")

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise fetching.requests.HTTPError(str(self.status_code))


class ArchiveFallback(unittest.TestCase):
    def setUp(self):
        self.cfg = cfg(archive_fallback=True, archive_max_age_days=30)
        self.requested = []

    def _archive(self, captured: datetime):
        stamp = captured.strftime("%Y%m%d%H%M%S")
        html = f"<html><body><article><p>{PAGE}</p></article></body></html>"

        def get(url, params=None, headers=None, timeout=None):
            self.requested.append(url)
            if url == fetching.ARCHIVE_AVAILABILITY_API:
                return ArchiveResponse(
                    {"archived_snapshots": {"closest": {"available": True, "status": "200", "timestamp": stamp}}}
                )
            return ArchiveResponse(text=html)

        patcher = mock.patch.object(fetching.requests, "get", get)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_a_capture_newer_than_the_last_read_is_used(self):
        now = datetime.now(timezone.utc)
        self._archive(now - timedelta(days=1))
        prior = {"last_success": (now - timedelta(days=5)).isoformat()}
        result = fetching._archive_fetch({"url": "https://www.digital.gov.au/a", "selector": "article"}, prior, self.cfg)
        self.assertTrue(result.ok, result.error)
        self.assertEqual(result.route, fetching.ROUTE_ARCHIVE)
        self.assertIn("Policy text", result.text)
        self.assertTrue(self.requested[1].startswith("https://web.archive.org/web/"))
        self.assertIn("id_/https://www.digital.gov.au/a", self.requested[1])

    def test_a_capture_older_than_the_last_read_is_refused(self):
        now = datetime.now(timezone.utc)
        self._archive(now - timedelta(days=5))
        prior = {"last_success": (now - timedelta(days=1)).isoformat()}
        result = fetching._archive_fetch({"url": "https://www.digital.gov.au/a"}, prior, self.cfg)
        self.assertFalse(result.ok)
        self.assertIn("no newer", result.error)
        self.assertEqual(len(self.requested), 1, "the page itself is never downloaded")

    def test_a_stale_capture_is_refused_even_for_a_new_document(self):
        self._archive(datetime.now(timezone.utc) - timedelta(days=90))
        result = fetching._archive_fetch({"url": "https://www.digital.gov.au/a"}, {}, self.cfg)
        self.assertFalse(result.ok)
        self.assertIn("too old", result.error)

    def test_it_is_only_asked_once_every_live_route_has_failed(self):
        routes = Routes(plain="hang", render=None)
        now = datetime.now(timezone.utc)
        self._archive(now - timedelta(hours=3))
        with mock.patch.object(fetching, "_http_fetch", routes.http), mock.patch.object(
            fetching, "_selenium_fetch", routes.selenium
        ), mock.patch.object(fetching, "_proxies", lambda: None):
            result = fetching.fetch_document({"url": "https://www.digital.gov.au/a"}, {}, self.cfg, session=fetching.FetchSession())
        self.assertTrue(result.ok)
        self.assertEqual(result.route, fetching.ROUTE_ARCHIVE)
        self.assertEqual([kind for kind, _ in routes.calls], ["plain", "render"])


if __name__ == "__main__":
    unittest.main()
