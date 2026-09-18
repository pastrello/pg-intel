from __future__ import annotations

from configparser import ConfigParser
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class DbConfig:
    dsn: str


@dataclass(frozen=True)
class AgentConfig:
    instance_name: str
    source: DbConfig
    repository: DbConfig
    interval_seconds: int = 60
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


def load_config(path: str | Path) -> AgentConfig:
    cp = ConfigParser()
    read = cp.read(path)
    if not read:
        raise FileNotFoundError(path)

    return AgentConfig(
        instance_name=_require(cp, "agent", "instance_name"),
        interval_seconds=cp.getint("agent", "interval_seconds", fallback=60),
        store_query_text=cp.getboolean("agent", "store_query_text", fallback=False),
        source=DbConfig(_require(cp, "source", "dsn")),
        repository=DbConfig(_require(cp, "repository", "dsn")),
        query_regression_ratio=cp.getfloat("analysis", "query_regression_ratio", fallback=3.0),
        query_regression_min_ms=cp.getfloat("analysis", "query_regression_min_ms", fallback=50.0),
        query_regression_min_calls=cp.getint("analysis", "query_regression_min_calls", fallback=5),
        dead_tuple_ratio=cp.getfloat("analysis", "dead_tuple_ratio", fallback=0.20),
        temp_bytes_alert=cp.getint("analysis", "temp_bytes_alert", fallback=1_073_741_824),
        large_unused_index_bytes=cp.getint("analysis", "large_unused_index_bytes", fallback=1_073_741_824),
    )
