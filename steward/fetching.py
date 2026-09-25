"""Document retrieval: conditional GET first, Selenium only when needed.

Two gates live here.

Stage 1, the metadata probe. Most days nothing changed, so a conditional GET
carrying `If-None-Match` / `If-Modified-Since` answers the question for the
price of one request header. A 304 ends the check for that document: no
browser, no extraction, no hash, no diff.

Stage 2 entry, extraction. Most monitored pages are static HTML, so the
default path is `requests` plus `trafilatura`, whose boilerplate removal
replaces the hand-maintained tag blacklist that was a standing source of
nav-and-whitespace noise. Selenium is reserved for URLs marked
`"render": true` in policy_sets.json, and for salvaging a plain fetch that
came back unusable.

Some hosts refuse plain HTTP clients outright. Several gov.au sites sit
behind a bot manager that lets a real browser through but holds a `requests`
connection open until it times out: on 25 September 2026 that was 31
documents on four hosts, each spending the full 30-second timeout before
Chrome read it in about five, or 15 of the run's 18 minutes. A FetchSession
remembers those hosts, so only the first document on one pays for finding
out, and it keeps one browser open for the whole run rather than launching
one per page. When every live route fails, the Internet Archive's
availability API is asked for a capture newer than the one already held.
"""

from __future__ import annotations

import logging
import os
import random
import time
import zlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional, Tuple
from urllib.parse import urlparse

import requests
import trafilatura
from bs4 import BeautifulSoup

from .content import fold_for_matching

log = logging.getLogger(__name__)

# Outcome codes.
OK = "ok"
NOT_MODIFIED = "not_modified"
FAILED = "failed"

# How the text was obtained, recorded so a change of extractor can be
# detected and re-baselined rather than reported as a policy amendment.
EXTRACTOR_TRAFILATURA = "trafilatura"
EXTRACTOR_SELECTOR = "selector+trafilatura"
EXTRACTOR_SELENIUM = "selenium+trafilatura"
EXTRACTOR_PDF = "pypdf"

# Which route produced the text.
ROUTE_PLAIN = "plain"
ROUTE_RENDER = "render"
ROUTE_ARCHIVE = "archive"

ARCHIVE_AVAILABILITY_API = "https://archive.org/wayback/available"


@dataclass
class FetchResult:
    url: str
    status: str
    text: str = ""
    etag: Optional[str] = None
    last_modified: Optional[str] = None
    http_status: Optional[int] = None
    extractor: Optional[str] = None
    error: str = ""
    attempts: int = 0
    duration_ms: int = 0
    notes: list[str] = field(default_factory=list)
    # The page as fetched, for a caller that needs its links. Never stored.
    html: str = ""
    route: str = ""
    # True when a plain GET was refused and a browser was needed; False when
    # plain HTTP worked; None when plain HTTP was not tried this time.
    plain_blocked: Optional[bool] = None
    # For an archive read, when the Internet Archive captured the page.
    archived_at: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.status == OK


def is_safe_url(url: str) -> bool:
    """Only plain http(s) URLs are ever navigated to.

    policy_sets.json is data; a `file://` or `javascript:` entry in it should
    not turn into local file access or script execution.
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        return False
    return parsed.scheme in ("http", "https") and bool(parsed.netloc)


def _conditional_headers(prior: dict, cfg) -> dict:
    headers = {
        "User-Agent": cfg.fetch.user_agent,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-AU,en;q=0.9",
    }
    if cfg.fetch.disable_conditional_get:
        return headers
    if prior.get("etag"):
        headers["If-None-Match"] = prior["etag"]
    if prior.get("last_modified"):
        headers["If-Modified-Since"] = prior["last_modified"]
    return headers


def _proxies() -> Optional[dict]:
    host, port, user, password = (
        os.environ.get(k) for k in ("PROXY_HOST", "PROXY_PORT", "PROXY_USER", "PROXY_PASS")
    )
    if not all([host, port, user, password]):
        return None
    endpoint = f"http://{user}:{password}@{host}:{port}"
    return {"http": endpoint, "https": endpoint}


# --- Session ---------------------------------------------------------------


class FetchSession:
    """What one run has learned about reaching each host, plus its browser.

    `blocked_hosts` maps a host to when a plain GET there was last refused.
    A document on one of those hosts goes straight to the browser. The
    orchestrator seeds it from the documents' stored `plain_blocked_at`, and
    entries older than `fetch.blocked_host_recheck_days` are left out so a
    host that stops refusing plain clients is noticed within a week or two.
    Each host's re-check is pushed back by a fixed, host-derived number of
    days (up to the recheck period again), so a hundred hosts first seen on
    the same day do not all pay for a plain-HTTP timeout on the same day.
    """

    def __init__(self, blocked_hosts: Optional[dict] = None):
        self.blocked_hosts: dict = dict(blocked_hosts or {})
        self._driver = None
        self._driver_failed = False

    @classmethod
    def remembering(
        cls,
        documents: Iterable[Tuple[str, dict]],
        recheck_days: int,
        now: Optional[datetime] = None,
    ) -> "FetchSession":
        """A session that already knows which hosts refused plain HTTP recently."""
        if recheck_days <= 0:
            return cls()
        now = now or datetime.now(timezone.utc)
        blocked: dict = {}
        for url, record in documents:
            stamp = _parse_time((record or {}).get("plain_blocked_at"))
            host = urlparse(url).hostname
            if not stamp or not host:
                continue
            stagger = zlib.crc32(host.encode("utf-8")) % recheck_days
            if stamp < now - timedelta(days=recheck_days + stagger):
                continue
            if host not in blocked or stamp > _parse_time(blocked[host]):
                blocked[host] = record["plain_blocked_at"]
        return cls(blocked)

    def is_blocked(self, url: str) -> bool:
        return urlparse(url).hostname in self.blocked_hosts

    def mark_blocked(self, url: str, when: str) -> None:
        host = urlparse(url).hostname
        if host:
            self.blocked_hosts[host] = when

    def driver(self, cfg):
        """The run's browser, started on first use. None if it cannot start."""
        if self._driver is None and not self._driver_failed:
            self._driver = initialize_driver(cfg)
            self._driver_failed = self._driver is None
        return self._driver

    def discard_driver(self) -> None:
        """Drop a browser that has errored; the next render starts a fresh one."""
        driver, self._driver = self._driver, None
        if driver is not None:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass

    def close(self) -> None:
        self.discard_driver()


def _parse_time(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


# --- Extraction ------------------------------------------------------------


def extract_text(html: str, url: str, selector: Optional[str] = None) -> tuple[str, str]:
    """Turn HTML into readable text. Returns (text, extractor_used)."""
    if selector:
        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(selector)
        if elements:
            fragment = "".join(str(el) for el in elements)
            text = trafilatura.extract(
                fragment,
                include_comments=False,
                include_tables=True,
                favor_recall=True,
                url=url,
            )
            if text and text.strip():
                return text, EXTRACTOR_SELECTOR
            # trafilatura declines very short or list-like fragments; the
            # selector already narrowed the page, so plain text is safe here.
            text = "\n".join(el.get_text(separator="\n", strip=True) for el in elements)
            if text.strip():
                return text, EXTRACTOR_SELECTOR
        else:
            log.warning("    Selector %r matched nothing at %s, using full page", selector, url)

    text = trafilatura.extract(
        html,
        include_comments=False,
        include_tables=True,
        favor_recall=True,
        url=url,
    )
    return (text or ""), EXTRACTOR_TRAFILATURA


def extract_pdf_text(data: bytes) -> str:
    """Text of a PDF, page by page. Empty if the file cannot be read."""
    from io import BytesIO

    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(BytesIO(data))
        return "\n".join((page.extract_text() or "") for page in reader.pages)
    except (PdfReadError, ValueError, KeyError, OSError) as exc:
        log.warning("    Could not read PDF: %s", exc)
        return ""


def _is_pdf(response) -> bool:
    content_type = (response.headers.get("Content-Type", "") or "").lower()
    return "application/pdf" in content_type or (response.content or b"")[:5] == b"%PDF-"


# --- Plain HTTP path -------------------------------------------------------


def decode_body(response) -> str:
    """Response body as text, without trusting requests' charset fallback.

    When a text/* response carries no charset, requests decodes it as
    ISO-8859-1. A UTF-8 em dash then becomes 'â' plus two control characters
    that extraction strips, so the same page read on two days could differ by
    nothing but that — which is how Google's AI Principles page kept reaching
    the model as a "change". A declared charset is honoured; otherwise UTF-8
    is tried first, and only bytes that are not valid UTF-8 fall back to
    detection.
    """
    content_type = response.headers.get("Content-Type", "") or ""
    if "charset=" in content_type.lower():
        return response.text

    raw = response.content or b""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        encoding = response.apparent_encoding or "utf-8"
        return raw.decode(encoding, errors="replace")



def _http_fetch(url_data: dict, prior: dict, cfg, use_proxy: bool) -> FetchResult:
    url = url_data["url"]
    proxies = _proxies() if use_proxy else None
    if use_proxy and proxies is None:
        return FetchResult(url, FAILED, error="proxy requested but credentials incomplete")

    try:
        response = requests.get(
            url,
            headers=_conditional_headers(prior, cfg),
            timeout=cfg.fetch.timeout_seconds,
            proxies=proxies,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        return FetchResult(url, FAILED, error=f"{type(exc).__name__}: {exc}")

    etag = response.headers.get("ETag")
    last_modified = response.headers.get("Last-Modified")

    if response.status_code == 304:
        return FetchResult(
            url,
            NOT_MODIFIED,
            etag=etag or prior.get("etag"),
            last_modified=last_modified or prior.get("last_modified"),
            http_status=304,
        )

    if response.status_code >= 400:
        return FetchResult(
            url, FAILED, http_status=response.status_code, error=f"HTTP {response.status_code}"
        )

    if _is_pdf(response):
        return FetchResult(
            url,
            OK,
            text=extract_pdf_text(response.content),
            etag=etag,
            last_modified=last_modified,
            http_status=response.status_code,
            extractor=EXTRACTOR_PDF,
            route=ROUTE_PLAIN,
        )

    html = decode_body(response)
    text, extractor = extract_text(html, url, url_data.get("selector"))
    return FetchResult(
        url,
        OK,
        text=text,
        etag=etag,
        last_modified=last_modified,
        http_status=response.status_code,
        extractor=extractor,
        html=html,
        route=ROUTE_PLAIN,
    )


# --- Internet Archive path -------------------------------------------------


def _archive_fetch(url_data: dict, prior: dict, cfg) -> FetchResult:
    """The newest Internet Archive capture, if it is newer than what we hold.

    Uses the Wayback Machine's availability API, then reads the capture's
    original bytes (the `id_` form, without the archive's toolbar). The
    archive fetches pages on its own schedule and is not blocked the way a
    datacenter client is, so it can see a page this run could not. Only a
    capture taken after this document's last successful read is accepted:
    an older one could only report a change backwards. The capture must also
    be within `fetch.archive_max_age_days`.
    """
    url = url_data["url"]
    try:
        response = requests.get(
            ARCHIVE_AVAILABILITY_API,
            params={"url": url},
            headers={"User-Agent": cfg.fetch.user_agent},
            timeout=cfg.fetch.timeout_seconds,
        )
        response.raise_for_status()
        closest = (response.json().get("archived_snapshots") or {}).get("closest") or {}
    except (requests.RequestException, ValueError) as exc:
        return FetchResult(url, FAILED, error=f"archive lookup failed: {type(exc).__name__}")

    captured = _parse_archive_timestamp(closest.get("timestamp"))
    if not closest.get("available") or str(closest.get("status")) != "200" or captured is None:
        return FetchResult(url, FAILED, error="no archived copy")

    now = datetime.now(timezone.utc)
    if captured < now - timedelta(days=cfg.fetch.archive_max_age_days):
        return FetchResult(url, FAILED, error=f"archived copy is from {captured.date()}, too old to use")
    last_success = _parse_time(prior.get("last_success"))
    if last_success and captured <= last_success:
        return FetchResult(url, FAILED, error=f"archived copy ({captured.date()}) is no newer than the last read")

    stamp = closest["timestamp"]
    try:
        page = requests.get(
            f"https://web.archive.org/web/{stamp}id_/{url}",
            headers={"User-Agent": cfg.fetch.user_agent},
            timeout=cfg.fetch.timeout_seconds,
        )
    except requests.RequestException as exc:
        return FetchResult(url, FAILED, error=f"archive read failed: {type(exc).__name__}")
    if page.status_code >= 400:
        return FetchResult(url, FAILED, http_status=page.status_code, error=f"archive read failed: HTTP {page.status_code}")

    if _is_pdf(page):
        html, text, extractor = "", extract_pdf_text(page.content), EXTRACTOR_PDF
    else:
        html = decode_body(page)
        text, extractor = extract_text(html, url, url_data.get("selector"))
    return FetchResult(
        url,
        OK,
        text=text,
        http_status=page.status_code,
        extractor=extractor,
        html=html,
        route=ROUTE_ARCHIVE,
        archived_at=captured.isoformat(),
    )


def _parse_archive_timestamp(value) -> Optional[datetime]:
    try:
        return datetime.strptime(str(value), "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


# --- Selenium path ---------------------------------------------------------


def _selenium_fetch(url_data: dict, cfg, use_proxy: bool, session: Optional[FetchSession] = None) -> FetchResult:
    """Render with headless Chrome. Imported lazily — a run where every URL
    is static should never pay for the Selenium import, let alone a browser.

    Direct renders share the session's browser; a proxied render gets its
    own, since the proxy is a launch option.
    """
    url = url_data["url"]

    try:
        from selenium.common.exceptions import TimeoutException, WebDriverException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        return FetchResult(url, FAILED, error=f"Selenium unavailable: {exc}")

    shared = session is not None and not use_proxy
    driver = session.driver(cfg) if shared else initialize_driver(cfg, with_proxy=use_proxy)
    if driver is None:
        return FetchResult(url, FAILED, error="could not start WebDriver")

    try:
        driver.get(url)
        WebDriverWait(driver, cfg.fetch.page_load_timeout).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        # A short settle for client-rendered pages. Deliberately brief: the
        # old 3-7s of sleeps per page bought nothing that this does not.
        time.sleep(random.uniform(0.8, 1.6))
        driver.execute_script("window.scrollTo(0, document.body.scrollHeight / 2);")
        time.sleep(random.uniform(0.4, 0.9))

        html = driver.page_source
        text, _ = extract_text(html, url, url_data.get("selector"))
        return FetchResult(url, OK, text=text, extractor=EXTRACTOR_SELENIUM, html=html, route=ROUTE_RENDER)
    except TimeoutException:
        return FetchResult(url, FAILED, error="timed out waiting for page body")
    except WebDriverException as exc:
        if shared:
            session.discard_driver()
        return FetchResult(url, FAILED, error=f"{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 — a scrape must not kill the run
        return FetchResult(url, FAILED, error=f"{type(exc).__name__}: {exc}")
    finally:
        if not shared:
            try:
                driver.quit()
            except Exception:  # noqa: BLE001
                pass


def initialize_driver(cfg, with_proxy: bool = False):
    from selenium import webdriver
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium_stealth import stealth
    from webdriver_manager.chrome import ChromeDriverManager

    options = webdriver.ChromeOptions()
    for argument in (
        "--headless=new",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-blink-features=AutomationControlled",
        "--disable-gpu",
        "--window-size=1920,1080",
        "--lang=en-US,en;q=0.9",
    ):
        options.add_argument(argument)
    options.add_argument(f"user-agent={cfg.fetch.user_agent}")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    if with_proxy:
        host, port, user, password = (
            os.environ.get(k)
            for k in ("PROXY_HOST", "PROXY_PORT", "PROXY_USER", "PROXY_PASS")
        )
        if not all([host, port, user, password]):
            log.warning("Proxy requested but credentials incomplete")
            return None
        options.add_argument(f"--proxy-server=http://{user}:{password}@{host}:{port}")

    try:
        service = ChromeService(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=options)
        stealth(
            driver,
            languages=["en-US", "en"],
            vendor="Google Inc.",
            platform="Win32",
            webgl_vendor="Intel Inc.",
            renderer="Intel Iris OpenGL Engine",
            fix_hairline=True,
        )
        return driver
    except Exception as exc:  # noqa: BLE001
        log.error("Failed to initialize WebDriver: %s", exc)
        return None


# --- Orchestration ---------------------------------------------------------


# Client errors that a browser might get past, because they are usually bot
# defences rather than a statement about the resource.
_RENDERABLE_STATUSES = {401, 403, 405, 406, 429}


def _worth_rendering(result: FetchResult) -> bool:
    """Whether a failed plain fetch is worth spending a browser launch on."""
    status = result.http_status
    if status is None:
        return True  # a network-level failure; a different route may work
    if 400 <= status < 500:
        return status in _RENDERABLE_STATUSES
    return True


def _looks_like_block_page(text: str, cfg) -> bool:
    folded = fold_for_matching(text)
    return any(fold_for_matching(sig) in folded for sig in cfg.validation.failure_signatures)


def fetch_document(
    url_data: dict,
    prior: dict,
    cfg,
    policy_set: Optional[dict] = None,
    session: Optional[FetchSession] = None,
) -> FetchResult:
    """Fetch one document, escalating only as far as it has to.

    Order: conditional plain GET -> Selenium (if the page needs rendering or
    the plain fetch was unusable) -> the same two through the proxy -> the
    newest Internet Archive capture. A host the session knows refuses plain
    HTTP skips straight to the browser.

    Without a session a throwaway one is used, so the browser is closed on
    return; pass the run's session to keep it open between documents.
    """
    if session is None:
        session = FetchSession()
        try:
            return fetch_document(url_data, prior, cfg, policy_set, session)
        finally:
            session.close()

    url = url_data["url"]
    started = time.monotonic()

    def done(result: FetchResult, attempts: int) -> FetchResult:
        result.attempts = attempts
        result.duration_ms = int((time.monotonic() - started) * 1000)
        return result

    if not is_safe_url(url):
        return FetchResult(url, FAILED, error="unsafe or malformed URL, refused")

    policy_set = policy_set or {}
    needs_render = bool(url_data.get("render") or policy_set.get("render"))
    force_proxy = bool(url_data.get("force_proxy") or policy_set.get("force_proxy"))
    known_blocked = session.is_blocked(url)

    result = FetchResult(url, FAILED, error="not attempted")
    attempts = 0

    for attempt in range(1, cfg.fetch.max_retries + 1):
        for use_proxy in ((True,) if force_proxy else (False, True)):
            if use_proxy and _proxies() is None:
                continue

            attempts += 1
            route = "proxy" if use_proxy else "direct"
            plain_refused = False

            if known_blocked and not use_proxy:
                # Its plain GET would only hang until the timeout, as it did
                # recently; the browser is what reads this host.
                log.info("    [%s] %s refuses plain clients — rendering", route, urlparse(url).hostname)
            elif not needs_render:
                log.info("    [%s] conditional GET %s", route, url)
                result = _http_fetch(url_data, prior, cfg, use_proxy)
                if result.status == NOT_MODIFIED:
                    log.info("    [%s] 304 Not Modified — nothing to do", route)
                    result.plain_blocked = False
                    return done(result, attempts)
                if result.ok and result.text.strip() and not _looks_like_block_page(result.text, cfg):
                    result.plain_blocked = False
                    return done(result, attempts)
                if result.ok:
                    result.notes.append("plain fetch returned unusable text, rendering")
                elif not _worth_rendering(result):
                    # A 404 is an answer, not a rendering problem. Launching a
                    # browser to re-read it costs ~20s and learns nothing.
                    log.warning("    [%s] %s — not worth rendering", route, result.error)
                    continue
                plain_refused = True
            else:
                # A cheap conditional probe still saves the browser launch.
                probe = _http_fetch({"url": url}, prior, cfg, use_proxy)
                if probe.status == NOT_MODIFIED:
                    log.info("    [%s] 304 Not Modified — no render needed", route)
                    probe.plain_blocked = False
                    return done(probe, attempts)
                plain_refused = probe.status == FAILED and _worth_rendering(probe)

            log.info("    [%s] rendering %s", route, url)
            rendered = _selenium_fetch(url_data, cfg, use_proxy, session)
            if rendered.ok and rendered.text.strip():
                # Carry validators forward from the probe so the next run can
                # still short-circuit on a 304.
                rendered.etag = result.etag or prior.get("etag")
                rendered.last_modified = result.last_modified or prior.get("last_modified")
                if plain_refused and not use_proxy:
                    rendered.plain_blocked = True
                    session.mark_blocked(url, datetime.now(timezone.utc).isoformat())
                return done(rendered, attempts)
            result = rendered if rendered.error else result

        if attempt < cfg.fetch.max_retries:
            log.warning(
                "  Retrying %s in %ds (attempt %d/%d)",
                url,
                cfg.fetch.retry_delay_seconds,
                attempt,
                cfg.fetch.max_retries,
            )
            time.sleep(cfg.fetch.retry_delay_seconds)

    if cfg.fetch.archive_fallback:
        archived = _archive_fetch(url_data, prior, cfg)
        if archived.ok and archived.text.strip() and not _looks_like_block_page(archived.text, cfg):
            log.info("    Read %s from the Internet Archive capture of %s", url, archived.archived_at)
            archived.notes.append(f"live routes failed: {result.error}")
            return done(archived, attempts + 1)
        log.info("    No usable archive copy of %s: %s", url, archived.error)

    if result.status != FAILED:
        result.status = FAILED
    return done(result, attempts)
