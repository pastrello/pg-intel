from __future__ import annotations

import json
import statistics
from dataclasses import dataclass
from typing import Any

from .config import AgentConfig
from .repository import insert_event


@dataclass
class Event:
    severity: str
    event_type: str
    object_type: str | None
    object_key: str | None
    title: str
    details: dict[str, Any]


def analyze_database(rows: list[dict[str, Any]], cfg: AgentConfig) -> list[Event]:
    events: list[Event] = []
    for r in rows:
        if r["deadlocks_delta"] > 0:
            events.append(Event(
                "critical", "deadlock", "database", r["datname"],
                f"{r['deadlocks_delta']} deadlock(s) detected in {r['datname']}",
                {"deadlocks_delta": r["deadlocks_delta"]},
            ))
        if r["temp_bytes_delta"] >= cfg.temp_bytes_alert:
            events.append(Event(
                "warning", "high_temp_io", "database", r["datname"],
                f"High temporary I/O in {r['datname']}",
                {"temp_bytes_delta": r["temp_bytes_delta"], "threshold": cfg.temp_bytes_alert},
            ))
        ratio = r.get("cache_hit_ratio")
        block_ops = r["blks_hit_delta"] + r["blks_read_delta"]
        if ratio is not None and block_ops >= 10_000 and ratio < 0.90:
            events.append(Event(
                "warning", "low_cache_hit", "database", r["datname"],
                f"Low interval cache-hit ratio in {r['datname']}",
                {"cache_hit_ratio": ratio, "block_operations": block_ops},
            ))
    return events


def analyze_tables(rows: list[dict[str, Any]], cfg: AgentConfig) -> list[Event]:
    events = []
    for r in rows:
        ratio = r.get("dead_tuple_ratio")
        # Ignore tiny tables where percentages are noisy.
        if ratio is not None and (r["n_live_tup"] + r["n_dead_tup"]) >= 10_000 and ratio >= cfg.dead_tuple_ratio:
            key = f"{r['schemaname']}.{r['relname']}"
            events.append(Event(
                "warning", "high_dead_tuple_ratio", "table", key,
                f"High dead-tuple ratio in {key}",
                {"dead_tuple_ratio": ratio, "n_live_tup": r["n_live_tup"], "n_dead_tup": r["n_dead_tup"]},
            ))
    return events


def analyze_indexes(rows: list[dict[str, Any]], cfg: AgentConfig) -> list[Event]:
    events = []
    for r in rows:
        if (
            r["index_size_bytes"] >= cfg.large_unused_index_bytes
            and int(r["idx_scan"] or 0) == 0
            and not r["indisprimary"]
            and not r["indisunique"]
        ):
            key = f"{r['schemaname']}.{r['indexrelname']}"
            events.append(Event(
                "info", "large_never_scanned_index", "index", key,
                f"Large index has zero scans since statistics reset: {key}",
                {"index_size_bytes": r["index_size_bytes"], "idx_scan": r["idx_scan"]},
            ))
    return events


def analyze_query_regressions(repo_conn, instance_id: int, rows: list[dict[str, Any]], cfg: AgentConfig) -> list[Event]:
    events = []
    for r in rows:
        current = r.get("mean_exec_time_ms")
        if current is None or r["calls_delta"] < cfg.query_regression_min_calls:
            continue
        with repo_conn.cursor() as cur:
            cur.execute(
                """
                SELECT mean_exec_time_ms
                FROM pgintel.query_samples
                WHERE instance_id = %s
                  AND dbid = %s AND userid = %s AND queryid = %s
                  AND mean_exec_time_ms IS NOT NULL
                  AND calls_delta >= %s
                ORDER BY collected_at DESC
                OFFSET 1 LIMIT 12
                """,
                (instance_id, r["dbid"], r["userid"], r["queryid"], cfg.query_regression_min_calls),
            )
            hist = [float(x["mean_exec_time_ms"]) for x in cur.fetchall()]
        if len(hist) < 5:
            continue
        baseline = statistics.median(hist)
        if baseline <= 0:
            continue
        ratio = current / baseline
        if current >= cfg.query_regression_min_ms and ratio >= cfg.query_regression_ratio:
            key = f"{r['dbid']}:{r['userid']}:{r['queryid']}"
            events.append(Event(
                "warning", "query_regression", "query", key,
                f"Query {r['queryid']} latency increased to {current:.2f} ms",
                {
                    "queryid": r["queryid"],
                    "current_mean_ms": current,
                    "baseline_median_ms": baseline,
                    "ratio": ratio,
                    "calls_delta": r["calls_delta"],
                    "query_hash": r.get("query_hash"),
                },
            ))
    return events


def persist_events(conn, instance_id: int, events: list[Event]) -> None:
    for e in events:
        insert_event(
            conn, instance_id, e.severity, e.event_type, e.object_type, e.object_key,
            e.title, json.dumps(e.details, default=str),
        )
