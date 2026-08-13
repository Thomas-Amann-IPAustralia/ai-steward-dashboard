"""Load and validate steward_config.yaml.

Thresholds the steward will want to tune belong in a file, not in constants
spread through main.py. Validation happens once at startup and fails fast with
a message naming the offending key.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, fields, is_dataclass
from typing import Any, Dict, List, get_args, get_origin, get_type_hints

import yaml

CONFIG_FILE = "steward_config.yaml"


class ConfigError(ValueError):
    """Raised when steward_config.yaml is missing, malformed or out of range."""


@dataclass
class FetchConfig:
    timeout_seconds: int = 30
    max_retries: int = 2
    retry_delay_seconds: int = 5
    page_load_timeout: int = 25
    disable_conditional_get: bool = False
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
class StewardConfig:
    model: str = "gemini-2.5-flash"
    fetch: FetchConfig = field(default_factory=FetchConfig)
    validation: ValidationConfig = field(default_factory=ValidationConfig)
    normalisation: NormalisationConfig = field(default_factory=NormalisationConfig)
    diff: DiffConfig = field(default_factory=DiffConfig)
    fingerprint: FingerprintConfig = field(default_factory=FingerprintConfig)
    health: HealthConfig = field(default_factory=HealthConfig)
    retention: RetentionConfig = field(default_factory=RetentionConfig)

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

    v = cfg.validation
    _check(v.min_length >= 0, "validation.min_length: must not be negative")
    _check(0 < v.shrink_ratio < 1, "validation.shrink_ratio: must be between 0 and 1 exclusive")
    _check(v.growth_ratio > 1, "validation.growth_ratio: must be greater than 1")
    _check(bool(v.failure_signatures), "validation.failure_signatures: must not be empty")

    d = cfg.diff
    _check(d.context_lines >= 0, "diff.context_lines: must not be negative")
    _check(d.max_diff_chars > 0, "diff.max_diff_chars: must be greater than 0")

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
