from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbConfig:
    dsn: str
    expected_major: int | None = None


@dataclass(frozen=True)
class AgentConfig:
    instance_name: str
    source: DbConfig
    repository: DbConfig
    interval_seconds: int = 60
    slow_interval_seconds: int = 900
    size_interval_seconds: int = 3600
    max_source_cycle_seconds: float = 20.0
    query_text_mode: str = "none"
    store_query_text: bool = False
    query_regression_ratio: float = 3.0
    query_regression_min_ms: float = 50.0
    query_regression_min_calls: int = 5
    dead_tuple_ratio: float = 0.20
    temp_bytes_alert: int = 1_073_741_824
    large_unused_index_bytes: int = 1_073_741_824


def _require(cp: ConfigParser, section: str, key: str) -> str:
    if not cp.has_option(section, key):
        raise ValueError(f"Missing configuration: [{section}] {key}")
    value = cp.get(section, key).strip()
    if not value:
        raise ValueError(f"Empty configuration: [{section}] {key}")
    return value


def _query_text_mode(cp: ConfigParser) -> str:
    if cp.has_option("collection", "query_text_mode"):
        mode = cp.get("collection", "query_text_mode").strip().lower()
    elif cp.getboolean("agent", "store_query_text", fallback=False):
        mode = "all"
    else:
        mode = "none"
    if mode not in {"none", "events", "all"}:
        raise ValueError("[collection] query_text_mode must be one of: none, events, all")
    return mode


def load_config(path: str | Path) -> AgentConfig:
    cp = ConfigParser()
    read = cp.read(path)
    if not read:
        raise FileNotFoundError(path)

    fast = cp.getint("agent", "interval_seconds", fallback=60)
    slow = cp.getint("collection", "slow_interval_seconds", fallback=900)
    sizes = cp.getint("collection", "size_interval_seconds", fallback=3600)
    budget = cp.getfloat("collection", "max_source_cycle_seconds", fallback=20.0)
    if fast < 10:
        raise ValueError("[agent] interval_seconds must be >= 10")
    if slow < fast:
        raise ValueError("[collection] slow_interval_seconds must be >= interval_seconds")
    if sizes < slow:
        raise ValueError("[collection] size_interval_seconds must be >= slow_interval_seconds")
    if budget <= 0:
        raise ValueError("[collection] max_source_cycle_seconds must be > 0")

    mode = _query_text_mode(cp)
    return AgentConfig(
        instance_name=_require(cp, "agent", "instance_name"),
        interval_seconds=fast,
        slow_interval_seconds=slow,
        size_interval_seconds=sizes,
        max_source_cycle_seconds=budget,
        query_text_mode=mode,
        store_query_text=(mode == "all"),
        source=DbConfig(
            _require(cp, "source", "dsn"),
            cp.getint("source", "expected_major") if cp.has_option("source", "expected_major") else None,
        ),
        repository=DbConfig(_require(cp, "repository", "dsn")),
        query_regression_ratio=cp.getfloat("analysis", "query_regression_ratio", fallback=3.0),
        query_regression_min_ms=cp.getfloat("analysis", "query_regression_min_ms", fallback=50.0),
        query_regression_min_calls=cp.getint("analysis", "query_regression_min_calls", fallback=5),
        dead_tuple_ratio=cp.getfloat("analysis", "dead_tuple_ratio", fallback=0.20),
        temp_bytes_alert=cp.getint("analysis", "temp_bytes_alert", fallback=1_073_741_824),
        large_unused_index_bytes=cp.getint("analysis", "large_unused_index_bytes", fallback=1_073_741_824),
    )
