"""The rules every outbound request follows, and the browser's launch options.

The pipeline fetches URLs other people choose — the DTA register's links, a
site's redirects — and publishes what comes back. These pin the guards:
nothing on a non-public address is fetched (at any redirect hop), a body is
never read past its cap, published error text carries no secrets, the proxy
password never reaches Chrome's command line, and Chrome keeps its sandbox
whenever it can start with one.
"""

from __future__ import annotations

from tests import offline  # noqa: F401 — no test may use the network
import http.server
import os
import socket
import threading
import unittest
from unittest import mock

import requests

from steward import fetching, web
from steward.config import load_config
from steward.proxyrelay import ProxyRelay


def resolves_to(address):
    return lambda host, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 0))]


class PublicAddresses(unittest.TestCase):
    def test_internal_addresses_are_refused(self):
        for address in ("127.0.0.1", "10.1.2.3", "172.16.0.9", "192.168.1.1", "169.254.169.254", "100.64.0.1", "0.0.0.0"):
            with mock.patch.object(web.socket, "getaddrinfo", resolves_to(address)):
                self.assertFalse(web.is_public_host("somewhere.example"), address)

    def test_a_public_address_is_allowed(self):
        with mock.patch.object(web.socket, "getaddrinfo", resolves_to("203.2.218.214")):
            self.assertTrue(web.is_public_host("www.ipaustralia.gov.au"))

    def test_only_http_and_https_are_destinations(self):
        for url in ("file:///etc/passwd", "javascript:alert(1)", "ftp://example.com/x", "https://"):
            with self.assertRaises(web.UnsafeDestination):
                web.check_destination(url)


class _Handler(http.server.BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):  # noqa: N802 — the stdlib's name
        status, headers, body = self.routes[self.path]
        self.send_response(status)
        for name, value in headers.items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


class Requests(unittest.TestCase):
    """Against a real HTTP server on this machine, treated as public."""

    def setUp(self):
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.base = f"http://127.0.0.1:{self.server.server_address[1]}"
        # 127.0.0.1 stands in for a public site; "internal.example" for an
        # address on the runner's own network.
        patcher = mock.patch.object(web, "is_public_host", lambda host: host == "127.0.0.1")
        patcher.start()
        self.addCleanup(patcher.stop)

    def get(self, path, max_bytes=1024 * 1024):
        return web.get(self.base + path, timeout=5, max_bytes=max_bytes)

    def test_redirects_are_followed(self):
        _Handler.routes = {
            "/old": (301, {"Location": "/new", "Content-Length": "0"}, b""),
            "/new": (200, {"Content-Length": "4"}, b"here"),
        }
        response = self.get("/old")
        self.assertEqual(response.text, "here")
        self.assertTrue(response.url.endswith("/new"))

    def test_a_redirect_to_an_internal_address_is_refused_before_connecting(self):
        _Handler.routes = {"/go": (302, {"Location": "http://internal.example/secrets", "Content-Length": "0"}, b"")}
        with self.assertRaises(web.UnsafeDestination):
            self.get("/go")

    def test_a_declared_oversized_body_is_refused(self):
        _Handler.routes = {"/big": (200, {"Content-Length": str(5 * 1024 * 1024)}, b"")}
        with self.assertRaises(web.ResponseTooLarge):
            self.get("/big")

    def test_an_undeclared_oversized_body_is_abandoned(self):
        _Handler.routes = {"/stream": (200, {}, b"x" * (2 * 1024 * 1024))}
        with self.assertRaises(web.ResponseTooLarge):
            self.get("/stream", max_bytes=1024 * 1024)

    def test_failures_are_requests_exceptions(self):
        # The callers catch requests.RequestException; the new refusals must be caught with it.
        self.assertTrue(issubclass(web.UnsafeDestination, requests.RequestException))
        self.assertTrue(issubclass(web.ResponseTooLarge, requests.RequestException))


class RefusedFetches(unittest.TestCase):
    def test_a_refused_or_oversized_response_is_not_retried_in_the_browser(self):
        cfg = load_config()
        cfg.fetch.max_retries = 1
        cfg.fetch.archive_fallback = False
        rendered = []
        for error in (web.UnsafeDestination("refused internal.example"), web.ResponseTooLarge("too big")):
            with mock.patch.object(fetching.web, "get", side_effect=error), mock.patch.object(
                fetching, "_selenium_fetch", lambda *a, **k: rendered.append(a) or fetching.FetchResult("u", fetching.OK)
            ), mock.patch.object(fetching, "_proxies", lambda: None):
                result = fetching.fetch_document({"url": "https://example.gov.au/a"}, {}, cfg, session=fetching.FetchSession())
            self.assertFalse(result.ok)
            self.assertIn(type(error).__name__, result.error)
        self.assertEqual(rendered, [])


class ErrorText(unittest.TestCase):
    def test_credentials_in_urls_are_removed(self):
        text = web.scrub_error("ProxyError: http://steward:hunter2@proxy.example:8080 refused")
        self.assertNotIn("hunter2", text)
        self.assertNotIn("steward:", text)

    def test_secret_values_are_masked(self):
        with mock.patch.dict(os.environ, {"PROXY_HOST": "proxy.internal.example", "PROXY_PASS": "s3cr3tpass"}):
            text = web.scrub_error("Cannot connect to proxy.internal.example with s3cr3tpass")
        self.assertNotIn("proxy.internal.example", text)
        self.assertNotIn("s3cr3tpass", text)

    def test_error_text_is_bounded(self):
        self.assertLessEqual(len(web.scrub_error("x " * 1000)), web.MAX_ERROR_CHARS)

    def test_describe_error_names_the_type(self):
        self.assertEqual(web.describe_error(ValueError("bad value")), "ValueError: bad value")


class _Upstream:
    """A stand-in for the real proxy: records what it was sent, then echoes."""

    def __init__(self):
        self.heads = []
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.port = self.listener.getsockname()[1]
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        with self.listener:
            conn, _ = self.listener.accept()
        with conn:
            data = b""
            while b"\r\n\r\n" not in data:
                data += conn.recv(4096)
            head, _, rest = data.partition(b"\r\n\r\n")
            self.heads.append(head)
            conn.sendall(b"HTTP/1.1 200 Connection established\r\n\r\n")
            payload = rest or conn.recv(4096)
            conn.sendall(payload)


class Relay(unittest.TestCase):
    def test_credentials_are_added_by_the_relay_not_the_browser(self):
        upstream = _Upstream()
        relay = ProxyRelay("127.0.0.1", upstream.port, "steward", "hunter2")
        address = relay.start()
        self.addCleanup(relay.close)
        host, port = address.split(":")

        with socket.create_connection((host, int(port)), timeout=5) as client:
            client.sendall(
                b"CONNECT www.digital.gov.au:443 HTTP/1.1\r\nHost: www.digital.gov.au:443\r\n"
                b"Proxy-Authorization: Basic c3B5OnNweQ==\r\n\r\n"
            )
            reply = b""
            while b"\r\n\r\n" not in reply:
                reply += client.recv(4096)
            self.assertIn(b"200", reply.split(b"\r\n")[0])
            client.sendall(b"tls bytes")
            self.assertEqual(client.recv(4096), b"tls bytes")

        (head,) = upstream.heads
        self.assertTrue(head.startswith(b"CONNECT www.digital.gov.au:443 HTTP/1.1"))
        self.assertIn(b"Proxy-Authorization: Basic c3Rld2FyZDpodW50ZXIy", head)
        self.assertNotIn(b"c3B5OnNweQ==", head, "whatever the client sent is replaced")


class FakeChrome:
    def __init__(self, options=None, **_):
        self.arguments = list(options.arguments)
        self.quit_calls = 0

    def quit(self):
        self.quit_calls += 1


class ChromeLaunch(unittest.TestCase):
    def setUp(self):
        self.cfg = load_config()
        self.launches = []
        fetching._sandbox_unavailable = False
        self.addCleanup(setattr, fetching, "_sandbox_unavailable", False)
        for patcher in (
            mock.patch("selenium.webdriver.Chrome", self._chrome),
            mock.patch("selenium_stealth.stealth", lambda *a, **k: None),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.refuse_sandbox = False
        self.flaky_launches = 0

    def _chrome(self, options=None, **kwargs):
        from selenium.common.exceptions import WebDriverException

        driver = FakeChrome(options)
        self.launches.append(driver.arguments)
        if self.flaky_launches:
            self.flaky_launches -= 1
            raise WebDriverException("chrome not reachable")
        if self.refuse_sandbox and "--no-sandbox" not in driver.arguments:
            raise WebDriverException("Running as root without --no-sandbox is not supported")
        return driver

    def test_chrome_starts_with_its_sandbox(self):
        driver = fetching.initialize_driver(self.cfg)
        self.assertIsNotNone(driver)
        self.assertNotIn("--no-sandbox", self.launches[0])

    def test_where_the_sandbox_cannot_start_chrome_still_runs_and_stops_retrying(self):
        self.refuse_sandbox = True
        self.assertIsNotNone(fetching.initialize_driver(self.cfg))
        self.assertIsNotNone(fetching.initialize_driver(self.cfg))
        sandboxed = [args for args in self.launches if "--no-sandbox" not in args]
        self.assertEqual(len(sandboxed), 2, "tried twice in the first launch, then not again this run")

    def test_one_flaky_launch_does_not_switch_the_sandbox_off(self):
        self.flaky_launches = 1
        self.assertIsNotNone(fetching.initialize_driver(self.cfg))
        self.assertIsNotNone(fetching.initialize_driver(self.cfg))
        self.assertFalse(any("--no-sandbox" in args for args in self.launches))

    def test_when_chrome_cannot_start_at_all_the_sandbox_is_not_given_up(self):
        self.flaky_launches = 3
        self.assertIsNone(fetching.initialize_driver(self.cfg))
        self.assertFalse(fetching._sandbox_unavailable)

    def test_the_proxy_password_never_reaches_the_command_line(self):
        env = {"PROXY_HOST": "proxy.example", "PROXY_PORT": "8080", "PROXY_USER": "steward", "PROXY_PASS": "hunter2"}
        with mock.patch.dict(os.environ, env):
            driver = fetching.initialize_driver(self.cfg, with_proxy=True)
        self.assertIsNotNone(driver)
        (arguments,) = self.launches
        self.assertFalse(any("hunter2" in a or "steward" in a for a in arguments), arguments)
        proxy = [a for a in arguments if a.startswith("--proxy-server=")]
        self.assertEqual(len(proxy), 1)
        self.assertTrue(proxy[0].startswith("--proxy-server=http://127.0.0.1:"))
        fetching.quit_driver(driver)
        self.assertEqual(driver.quit_calls, 1)


def text_pdf(pages):
    """A minimal PDF whose pages each say which page they are."""
    objects = [
        b"<</Type/Catalog/Pages 2 0 R>>",
        b"<</Type/Pages/Kids[%s]/Count %d>>" % (b" ".join(b"%d 0 R" % (4 + 2 * i) for i in range(pages)), pages),
        b"<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    for i in range(pages):
        content = b"BT /F1 12 Tf 72 712 Td (Page %d of the statement) Tj ET" % (i + 1)
        objects.append(b"<</Type/Page/Parent 2 0 R/MediaBox[0 0 612 792]/Resources<</Font<</F1 3 0 R>>>>/Contents %d 0 R>>" % (5 + 2 * i))
        objects.append(b"<</Length %d>>stream\n" % len(content) + content + b"\nendstream")
    out, offsets = bytearray(b"%PDF-1.4\n"), []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % number + body + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1) + b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer<</Size %d/Root 1 0 R>>\nstartxref\n%d\n%%%%EOF\n" % (len(objects) + 1, xref)
    return bytes(out)


class Pdfs(unittest.TestCase):
    def test_the_text_of_every_page_is_read(self):
        self.assertEqual(
            fetching.extract_pdf_text(text_pdf(3)),
            "Page 1 of the statement\nPage 2 of the statement\nPage 3 of the statement",
        )

    def test_only_the_first_pages_of_a_very_long_pdf_are_read(self):
        with mock.patch.object(fetching, "MAX_PDF_PAGES", 2):
            self.assertNotIn("Page 3", fetching.extract_pdf_text(text_pdf(3)))

    def test_an_unreadable_pdf_is_empty_text_not_an_exception(self):
        self.assertEqual(fetching.extract_pdf_text(b"%PDF-1.4\n garbage"), "")

    def test_errors_outside_pdfreaderror_are_caught_too(self):
        from pypdf.errors import LimitReachedError, ParseError

        for error in (LimitReachedError("stream too large"), ParseError("bad token"), RecursionError()):
            with mock.patch("pypdf.PdfReader", side_effect=error):
                self.assertEqual(fetching.extract_pdf_text(b"%PDF-1.7"), "", type(error).__name__)


if __name__ == "__main__":
    unittest.main()
