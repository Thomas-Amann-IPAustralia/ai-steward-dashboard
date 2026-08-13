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
"""

from __future__ import annotations

import logging
import os
import random
import time
from dataclasses import dataclass, field
from typing import Optional
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


# --- Plain HTTP path -------------------------------------------------------


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

    html = response.text
    text, extractor = extract_text(html, url, url_data.get("selector"))
    return FetchResult(
        url,
        OK,
        text=text,
        etag=etag,
        last_modified=last_modified,
        http_status=response.status_code,
        extractor=extractor,
    )


# --- Selenium path ---------------------------------------------------------


def _selenium_fetch(url_data: dict, cfg, use_proxy: bool) -> FetchResult:
    """Render with headless Chrome. Imported lazily — a run where every URL
    is static should never pay for the Selenium import, let alone a browser."""
    url = url_data["url"]

    try:
        from selenium.common.exceptions import TimeoutException, WebDriverException
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support import expected_conditions as EC
        from selenium.webdriver.support.ui import WebDriverWait
    except ImportError as exc:
        return FetchResult(url, FAILED, error=f"Selenium unavailable: {exc}")

    driver = initialize_driver(cfg, with_proxy=use_proxy)
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
        return FetchResult(url, OK, text=text, extractor=EXTRACTOR_SELENIUM)
    except TimeoutException:
        return FetchResult(url, FAILED, error="timed out waiting for page body")
    except WebDriverException as exc:
        return FetchResult(url, FAILED, error=f"{type(exc).__name__}")
    except Exception as exc:  # noqa: BLE001 — a scrape must not kill the run
        return FetchResult(url, FAILED, error=f"{type(exc).__name__}: {exc}")
    finally:
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


def fetch_document(url_data: dict, prior: dict, cfg, policy_set: Optional[dict] = None) -> FetchResult:
    """Fetch one document, escalating only as far as it has to.

    Order: conditional plain GET -> Selenium (if the page needs rendering or
    the plain fetch was unusable) -> the same two through the proxy.
    """
    url = url_data["url"]
    started = time.monotonic()

    if not is_safe_url(url):
        return FetchResult(url, FAILED, error="unsafe or malformed URL, refused")

    policy_set = policy_set or {}
    needs_render = bool(url_data.get("render") or policy_set.get("render"))
    force_proxy = bool(url_data.get("force_proxy") or policy_set.get("force_proxy"))

    result = FetchResult(url, FAILED, error="not attempted")
    attempts = 0

    for attempt in range(1, cfg.fetch.max_retries + 1):
        for use_proxy in ((True,) if force_proxy else (False, True)):
            if use_proxy and _proxies() is None:
                continue

            attempts += 1
            route = "proxy" if use_proxy else "direct"

            if not needs_render:
                log.info("    [%s] conditional GET %s", route, url)
                result = _http_fetch(url_data, prior, cfg, use_proxy)
                if result.status == NOT_MODIFIED:
                    log.info("    [%s] 304 Not Modified — nothing to do", route)
                    result.attempts = attempts
                    result.duration_ms = int((time.monotonic() - started) * 1000)
                    return result
                if result.ok and result.text.strip() and not _looks_like_block_page(result.text, cfg):
                    result.attempts = attempts
                    result.duration_ms = int((time.monotonic() - started) * 1000)
                    return result
                if result.ok:
                    result.notes.append("plain fetch returned unusable text, rendering")
                elif not _worth_rendering(result):
                    # A 404 is an answer, not a rendering problem. Launching a
                    # browser to re-read it costs ~20s and learns nothing.
                    log.warning("    [%s] %s — not worth rendering", route, result.error)
                    continue
            else:
                # A cheap conditional probe still saves the browser launch.
                probe = _http_fetch({"url": url}, prior, cfg, use_proxy)
                if probe.status == NOT_MODIFIED:
                    log.info("    [%s] 304 Not Modified — no render needed", route)
                    probe.attempts = attempts
                    probe.duration_ms = int((time.monotonic() - started) * 1000)
                    return probe

            log.info("    [%s] rendering %s", route, url)
            rendered = _selenium_fetch(url_data, cfg, use_proxy)
            if rendered.ok and rendered.text.strip():
                # Carry validators forward from the probe so the next run can
                # still short-circuit on a 304.
                rendered.etag = result.etag or prior.get("etag")
                rendered.last_modified = result.last_modified or prior.get("last_modified")
                rendered.attempts = attempts
                rendered.duration_ms = int((time.monotonic() - started) * 1000)
                return rendered
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

    result.attempts = attempts
    result.duration_ms = int((time.monotonic() - started) * 1000)
    if result.status != FAILED:
        result.status = FAILED
    return result
