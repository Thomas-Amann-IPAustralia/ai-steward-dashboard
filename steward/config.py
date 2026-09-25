"""Load and validate steward_config.yaml.

Thresholds the steward will want to tune belong in a file, not in constants
spread through main.py. Validation happens once at startup and fails fast with
a message naming the offending key.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, get_args, get_origin, get_type_hints

import yaml

CONFIG_FILE = "steward_config.yaml"

_HOST = re.compile(r"^[a-z0-9](?:[a-z0-9-]*[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]*[a-z0-9])?)+$")
# At least two labels, so a bare ".au" cannot open a whole country.
_HOST_SUFFIX = re.compile(r"^\.[a-z0-9-]+\.[a-z0-9.-]*[a-z0-9]$")


class ConfigError(ValueError):
    """Raised when steward_config.yaml is missing, malformed or out of range."""


@dataclass
class FetchConfig:
    timeout_seconds: int = 30
    max_retries: int = 2
    retry_delay_seconds: int = 5
    page_load_timeout: int = 25
    disable_conditional_get: bool = False
    # Days a host that refused plain HTTP is sent straight to the browser
    # before plain HTTP is tried there again. 0 turns the memory off.
    blocked_host_recheck_days: int = 7
    # Whether a document no live route could read is looked up in the
    # Internet Archive, and how old a capture may be to be used.
    archive_fallback: bool = True
    archive_max_age_days: int = 30
    # Most megabytes of one response that are read (after decompression);
    # anything larger is abandoned as a failed fetch.
    max_response_mb: int = 20
    user_agent: str = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
    )


@dataclass
class ValidationConfig:
    min_length: int = 500
    shrink_ratio: float = 0.6
    growth_ratio: float = 2.5
    failure_signatures: List[str] = field(default_factory=list)


@dataclass
class NormalisationConfig:
    noise_patterns: List[str] = field(default_factory=list)
    per_source_noise: Dict[str, List[str]] = field(default_factory=dict)


@dataclass
class DiffConfig:
    context_lines: int = 3
    max_diff_chars: int = 40000
    revert_memory: int = 5


@dataclass
class FingerprintConfig:
    watchlist: List[str] = field(default_factory=list)


@dataclass
class HealthConfig:
    consecutive_failure_threshold: int = 3
    error_rate_threshold: float = 0.3
    schema_failure_threshold: int = 2


@dataclass
class RetentionConfig:
    log_days: int = 365
    run_log_days: int = 90


@dataclass
class NewsConfig:
    enabled: bool = True
    # Days an item stays in news/feed.json before moving to the monthly archive.
    window_days: int = 45
    # Items below this relevance (0-3) are not kept at all.
    min_relevance: int = 1
    # Bound on what one source can add in one run.
    max_new_items_per_source: int = 40
    # Whether the model writes TLDRs and refines relevance.
    enrich: bool = True
    enrich_batch_size: int = 20
    max_enrich_items: int = 120
    ai_terms: List[str] = field(default_factory=list)
    australia_terms: List[str] = field(default_factory=list)
    government_terms: List[str] = field(default_factory=list)
    policy_terms: List[str] = field(default_factory=list)
    risk_terms: List[str] = field(default_factory=list)
    # Regexes; an item whose headline matches one is dropped before scoring.
    exclude_title_patterns: List[str] = field(default_factory=list)


@dataclass
class TransparencyConfig:
    enabled: bool = True
    register_url: str = "https://www.digital.gov.au/policy/ai/list-of-transparency-statements"
    register_selector: str = "article"
    # A register read that finds fewer statement links than this, or fewer
    # than keep_ratio of the list already held, or more than
    # max_new_statements agencies it has never listed before, is rejected.
    min_statements: int = 50
    keep_ratio: float = 0.8
    max_new_statements: int = 25
    # The register is a remote page, so which sites a run visits is decided
    # by whoever can edit it. A statement is only fetched on a host ending in
    # one of these suffixes or named in allowed_hosts; any other is listed
    # with an error until someone adds its host here.
    allowed_host_suffixes: List[str] = field(default_factory=lambda: [".gov.au"])
    allowed_hosts: List[str] = field(default_factory=list)
    # Seconds a plain GET to an agency's site may take before the browser is
    # tried; shorter than fetch.timeout_seconds because there are ~140 sites.
    fetch_timeout_seconds: int = 12
    # Whether the model says what changed in a statement, and how many
    # changed statements go in one call.
    summarise: bool = True
    summary_batch_size: int = 10
    # Most characters of one statement's diff shown to the model.
    max_diff_chars: int = 8000
    # Days register and statement events are kept.
    event_days: int = 365


@dataclass
class StewardConfig:
    model: str = "gemini-2.5-flash"
    fetch: FetchConfig = field(default_factory=FetchConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    normalisation: NormalisationConfig = field(default_factory=NormalisationConfig)
    diff: DiffConfig = field(default_factory=DiffConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)
    news: NewsConfig = field(default_factory=NewsConfig)
    transparency: TransparencyConfig = field(default_factory=TransparencyConfig)

    def noise_patterns_for(self, host: str) -> List[str]:
        """Global noise patterns plus any registered for this host."""
        patterns = list(self.normalisation.noise_patterns)
        patterns.extend(self.normalisation.per_source_noise.get(host, []))
        return patterns


# --- Generic builder -------------------------------------------------------


def _type_name(tp: Any) -> str:
    return getattr(tp, "__name__", str(tp))


def _coerce(value: Any, tp: Any, path: str) -> Any:
    origin = get_origin(tp)

    if origin is list:
        if not isinstance(value, list):
            raise ConfigError(f"{path}: expected a list, got {type(value).__name__}")
        (item_tp,) = get_args(tp)
        return [_coerce(item, item_tp, f"{path}[{i}]") for i, item in enumerate(value)]

    if origin is dict:
        if not isinstance(value, dict):
            raise ConfigError(f"{path}: expected a mapping, got {type(value).__name__}")
        key_tp, val_tp = get_args(tp)
        return {
            _coerce(k, key_tp, f"{path}.<key>"): _coerce(v, val_tp, f"{path}.{k}")
            for k, v in value.items()
        }

    if tp is bool:
        if not isinstance(value, bool):
            raise ConfigError(f"{path}: expected true or false, got {value!r}")
        return value

    if tp is int:
        # bool is an int subclass; reject it explicitly so `true` is not 1.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ConfigError(f"{path}: expected a whole number, got {value!r}")
        return value

    if tp is float:
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ConfigError(f"{path}: expected a number, got {value!r}")
        return float(value)

    if tp is str:
        if not isinstance(value, str):
            raise ConfigError(f"{path}: expected a string, got {value!r}")
        return value

    if is_dataclass(tp):
        return _build(tp, value, path)

    raise ConfigError(f"{path}: unsupported config type {_type_name(tp)}")


def _build(cls: Any, data: Any, path: str = "") -> Any:
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ConfigError(f"{path or '<root>'}: expected a mapping, got {type(data).__name__}")

    # `from __future__ import annotations` turns field.type into a string, so
    # resolve the real types rather than trusting the dataclass metadata.
    hints = get_type_hints(cls)
    known = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - known)
    if unknown:
        where = path or "<root>"
        raise ConfigError(
            f"{where}: unknown key(s) {', '.join(unknown)}. "
            f"Known keys: {', '.join(sorted(known))}"
        )

    kwargs = {}
    for name in known:
        if name not in data:
            continue
        child = f"{path}.{name}" if path else name
        kwargs[name] = _coerce(data[name], hints[name], child)
    return cls(**kwargs)


# --- Range checks ----------------------------------------------------------


def _check(condition: bool, message: str) -> None:
    if not condition:
        raise ConfigError(message)


def validate(cfg: StewardConfig) -> StewardConfig:
    _check(bool(cfg.model.strip()), "model: must not be empty")

    f = cfg.fetch
    _check(f.timeout_seconds > 0, "fetch.timeout_seconds: must be greater than 0")
    _check(f.max_retries >= 1, "fetch.max_retries: must be at least 1")
    _check(f.retry_delay_seconds >= 0, "fetch.retry_delay_seconds: must not be negative")
    _check(f.page_load_timeout > 0, "fetch.page_load_timeout: must be greater than 0")
    _check(bool(f.user_agent.strip()), "fetch.user_agent: must not be empty")
    _check(
        0 <= f.blocked_host_recheck_days <= 90,
        "fetch.blocked_host_recheck_days: must be between 0 and 90",
    )
    _check(
        1 <= f.archive_max_age_days <= 365,
        "fetch.archive_max_age_days: must be between 1 and 365",
    )
    _check(1 <= f.max_response_mb <= 200, "fetch.max_response_mb: must be between 1 and 200")

    v = cfg.validation
    _check(v.min_length >= 0, "validation.min_length: must not be negative")
    _check(0 < v.shrink_ratio < 1, "validation.shrink_ratio: must be between 0 and 1 exclusive")
    _check(v.growth_ratio > 1, "validation.growth_ratio: must be greater than 1")
    _check(bool(v.failure_signatures), "validation.failure_signatures: must not be empty")

    d = cfg.diff
    _check(d.context_lines >= 0, "diff.context_lines: must not be negative")
    _check(d.max_diff_chars > 0, "diff.max_diff_chars: must be greater than 0")
    _check(0 <= d.revert_memory <= 50, "diff.revert_memory: must be between 0 and 50")

    h = cfg.health
    _check(
        h.consecutive_failure_threshold >= 1,
        "health.consecutive_failure_threshold: must be at least 1",
    )
    _check(
        0 < h.error_rate_threshold <= 1,
        "health.error_rate_threshold: must be greater than 0 and at most 1",
    )
    _check(
        h.schema_failure_threshold >= 1,
        "health.schema_failure_threshold: must be at least 1",
    )

    r = cfg.retention
    _check(r.log_days > 0, "retention.log_days: must be greater than 0")
    _check(r.run_log_days > 0, "retention.run_log_days: must be greater than 0")

    n = cfg.news
    _check(1 <= n.window_days <= 365, "news.window_days: must be between 1 and 365")
    _check(0 <= n.min_relevance <= 3, "news.min_relevance: must be between 0 and 3")
    _check(n.max_new_items_per_source >= 1, "news.max_new_items_per_source: must be at least 1")
    _check(1 <= n.enrich_batch_size <= 50, "news.enrich_batch_size: must be between 1 and 50")
    _check(n.max_enrich_items >= 0, "news.max_enrich_items: must not be negative")
    _check(bool(n.ai_terms), "news.ai_terms: must not be empty")
    for i, pattern in enumerate(n.exclude_title_patterns):
        try:
            re.compile(pattern)
        except re.error as exc:
            raise ConfigError(f"news.exclude_title_patterns[{i}]: not a valid regex ({exc})") from exc

    t = cfg.transparency
    _check(t.register_url.startswith("https://"), "transparency.register_url: must be an https URL")
    _check(t.min_statements >= 1, "transparency.min_statements: must be at least 1")
    _check(0 < t.keep_ratio <= 1, "transparency.keep_ratio: must be greater than 0 and at most 1")
    _check(t.max_new_statements >= 1, "transparency.max_new_statements: must be at least 1")
    for i, suffix in enumerate(t.allowed_host_suffixes):
        _check(
            bool(_HOST_SUFFIX.match(suffix)),
            f"transparency.allowed_host_suffixes[{i}]: must be a lower-case domain suffix starting with a dot, like .gov.au",
        )
    for i, host in enumerate(t.allowed_hosts):
        _check(
            bool(_HOST.match(host)),
            f"transparency.allowed_hosts[{i}]: must be a lower-case host name, like www.csiro.au (no scheme or path)",
        )
    _check(t.fetch_timeout_seconds > 0, "transparency.fetch_timeout_seconds: must be greater than 0")
    _check(1 <= t.summary_batch_size <= 30, "transparency.summary_batch_size: must be between 1 and 30")
    _check(t.max_diff_chars >= 500, "transparency.max_diff_chars: must be at least 500")
    _check(t.event_days >= 1, "transparency.event_days: must be at least 1")

    return cfg


def load_config(path: str = CONFIG_FILE) -> StewardConfig:
    """Read, parse and validate the config file, or raise ConfigError."""
    if not os.path.exists(path):
        raise ConfigError(f"Config file '{path}' not found.")

    try:
        with open(path, "r", encoding="utf-8") as handle:
            raw = yaml.safe_load(handle)
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file '{path}' is not valid YAML: {exc}") from exc

    return validate(_build(StewardConfig, raw))
