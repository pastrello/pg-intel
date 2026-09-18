from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Callable, TypeVar

from .analyzer import (
    analyze_database,
    analyze_indexes,
    analyze_query_regressions,
    analyze_tables,
    persist_events,
)
from .capabilities import assess_source, major_from_version_num, validate_major
from .collectors import database, indexes, server, statements, tables
from .config import AgentConfig
from .db import connect
from .repository import (
    ensure_instance,
    insert_collection_cycle,
    insert_database_samples,
    insert_index_samples,
    insert_query_samples,
    insert_server_sample,
    insert_table_samples,
    migrate_repository as apply_repository_migration,
    repository_schema_info,
    update_query_texts,
)

LOG = logging.getLogger("pgintel")
T = TypeVar("T")


def _timed(metrics: dict[str, float], name: str, fn: Callable[[], T]) -> T:
    started = time.perf_counter()
    try:
        return fn()
    finally:
        metrics[name] = round((time.perf_counter() - started) * 1000.0, 3)


def _source_duration_ms(metrics: dict[str, float]) -> float:
    return round(sum(v for k, v in metrics.items() if k.startswith("source.")), 3)


def _repository_duration_ms(metrics: dict[str, float]) -> float:
    return round(sum(v for k, v in metrics.items() if k.startswith("repository.")), 3)


def _budget_exceeded(metrics: dict[str, float], cfg: AgentConfig) -> bool:
    return _source_duration_ms(metrics) >= cfg.max_source_cycle_seconds * 1000.0


def check(cfg: AgentConfig) -> dict:
    result = {
        "source": False,
        "repository": False,
        "repository_schema_0_1_4": False,
        "pg_stat_database_compatible": None,
        "pg_stat_statements": False,
        "pg_stat_statements_compatible": None,
    }
    with connect(cfg.source.dsn) as src:
        s = server.collect(src)
        major = major_from_version_num(s["server_version_num"])
        support = assess_source(src, expected_major=cfg.source.expected_major)
        result["source"] = True
        result["server_version"] = s["server_version"]
        result["server_major"] = major
        result["supported_range"] = support["support"]["supported_range"]
        result["pgintel_support_level"] = support["support"]["level"]
        result["expected_major"] = cfg.source.expected_major
        result["expected_major_match"] = support["support"]["expected_major_match"]
        result["postgresql_lifecycle"] = support["lifecycle"]

        db_compat = database.compatibility_info(src)
        result["pg_stat_database_compatible"] = db_compat["compatible"]
        result["pg_stat_database_session_statistics"] = db_compat["session_statistics"]
        result["pg_stat_database_parallel_worker_statistics"] = db_compat["parallel_worker_statistics"]
        result["pg_stat_database_missing_columns"] = db_compat["missing_required_columns"]

        result["pg_stat_statements"] = statements.extension_available(src)
        if result["pg_stat_statements"]:
            compat = statements.compatibility_info(src)
            result["pg_stat_statements_compatible"] = compat["compatible"]
            result["pg_stat_statements_layout"] = compat["io_timing_layout"]
            result["query_text_mode"] = cfg.query_text_mode
            result["pg_stat_statements_missing_columns"] = compat["missing_required_columns"]

    with connect(cfg.repository.dsn) as repo:
        schema = repository_schema_info(repo)
        result["repository"] = schema["core"]
        result["repository_schema_0_1_4"] = schema["production_safety"]
    return result


def capability_report(cfg: AgentConfig) -> dict:
    with connect(cfg.source.dsn) as src:
        return assess_source(src, expected_major=cfg.source.expected_major)


def migrate_repository(cfg: AgentConfig) -> None:
    with connect(cfg.repository.dsn) as repo:
        schema = repository_schema_info(repo)
        if not schema["core"]:
            raise RuntimeError("Core repository schema is missing; apply sql/001_repository.sql first")
        apply_repository_migration(repo)


def _event_query_keys(events) -> set[tuple[int, int, int]]:
    keys: set[tuple[int, int, int]] = set()
    for event in events:
        if event.event_type != "query_regression" or not event.object_key:
            continue
        try:
            dbid, userid, queryid = (int(x) for x in event.object_key.split(":", 2))
        except (TypeError, ValueError):
            continue
        keys.add((dbid, userid, queryid))
    return keys


def collect_once(
    cfg: AgentConfig,
    *,
    collect_slow: bool = True,
    collect_sizes: bool = True,
) -> dict[str, Any]:
    collected_at = datetime.now(timezone.utc)
    cycle_started = time.monotonic()
    collector_ms: dict[str, float] = {}
    notes: dict[str, Any] = {}

    with connect(cfg.source.dsn) as src, connect(cfg.repository.dsn) as repo:
        schema = repository_schema_info(repo)
        if not schema["production_safety"]:
            raise RuntimeError(
                "Repository migration 0.1.4 is missing; run 'pgintel migrate-repository' before collection"
            )

        server_row = _timed(collector_ms, "source.server", lambda: server.collect(src))
        major = major_from_version_num(server_row["server_version_num"])
        validate_major(major, cfg.source.expected_major)

        db_rows = _timed(
            collector_ms,
            "source.database",
            lambda: database.collect(src, include_size=collect_sizes),
        )

        pgss_available = statements.extension_available(src)
        query_rows = []
        if pgss_available:
            query_rows = _timed(
                collector_ms,
                "source.statements",
                lambda: statements.collect(src, include_query_text=(cfg.query_text_mode == "all")),
            )

        budget_exceeded = _budget_exceeded(collector_ms, cfg)
        want_objects = collect_slow or collect_sizes
        slow_collected = False
        sizes_collected = False
        table_rows = []
        index_rows = []
        if want_objects and not budget_exceeded:
            table_rows = _timed(
                collector_ms,
                "source.tables",
                lambda: tables.collect(src, include_size=collect_sizes),
            )
            budget_exceeded = _budget_exceeded(collector_ms, cfg)
            if not budget_exceeded:
                index_rows = _timed(
                    collector_ms,
                    "source.indexes",
                    lambda: indexes.collect(src, include_size=collect_sizes),
                )
                slow_collected = True
                sizes_collected = bool(collect_sizes)
            else:
                notes["indexes_skipped"] = "source cycle budget exceeded after table collection"
        elif want_objects:
            notes["slow_collectors_skipped"] = "source cycle budget exceeded after fast collectors"

        source_duration_ms = _source_duration_ms(collector_ms)
        budget_exceeded = budget_exceeded or _budget_exceeded(collector_ms, cfg)

        instance_id = _timed(
            collector_ms, "repository.instance", lambda: ensure_instance(repo, cfg.instance_name, server_row)
        )
        _timed(collector_ms, "repository.server", lambda: insert_server_sample(repo, instance_id, server_row))
        derived_db = _timed(
            collector_ms, "repository.database", lambda: insert_database_samples(repo, instance_id, collected_at, db_rows)
        )
        derived_tables = _timed(
            collector_ms, "repository.tables", lambda: insert_table_samples(repo, instance_id, collected_at, table_rows)
        ) if table_rows else []
        derived_indexes = _timed(
            collector_ms, "repository.indexes", lambda: insert_index_samples(repo, instance_id, collected_at, index_rows)
        ) if index_rows else []
        derived_queries = _timed(
            collector_ms,
            "repository.statements",
            lambda: insert_query_samples(
                repo,
                instance_id,
                collected_at,
                query_rows,
                store_query_text=(cfg.query_text_mode == "all"),
            ),
        ) if query_rows else []

        events = []
        events.extend(analyze_database(derived_db, cfg))
        if derived_tables:
            events.extend(analyze_tables(derived_tables, cfg))
        if derived_indexes and collect_sizes:
            events.extend(analyze_indexes(derived_indexes, cfg))
        query_events = analyze_query_regressions(repo, instance_id, derived_queries, cfg)
        events.extend(query_events)

        if cfg.query_text_mode == "events":
            keys = _event_query_keys(query_events)
            if keys and not _budget_exceeded(collector_ms, cfg):
                texts = _timed(
                    collector_ms,
                    "source.statement_text_events",
                    lambda: statements.fetch_query_texts(src, keys),
                )
                updated = _timed(
                    collector_ms,
                    "repository.statement_text_events",
                    lambda: update_query_texts(repo, instance_id, collected_at, texts),
                )
                notes["event_query_texts_updated"] = updated
            elif keys:
                notes["event_query_texts_skipped"] = "source cycle budget exceeded"

        _timed(collector_ms, "repository.events", lambda: persist_events(repo, instance_id, events))
        source_duration_ms = _source_duration_ms(collector_ms)
        repository_duration_ms = _repository_duration_ms(collector_ms)
        budget_exceeded = budget_exceeded or _budget_exceeded(collector_ms, cfg)
        cycle_duration_ms = round((time.monotonic() - cycle_started) * 1000.0, 3)
        metrics = {
            "instance_id": instance_id,
            "collected_at": collected_at,
            "cycle_duration_ms": cycle_duration_ms,
            "source_duration_ms": source_duration_ms,
            "repository_duration_ms": repository_duration_ms,
            "slow_requested": bool(collect_slow),
            "slow_collected": slow_collected,
            "sizes_requested": bool(collect_sizes),
            "sizes_collected": sizes_collected,
            "budget_exceeded": budget_exceeded,
            "database_rows": len(db_rows),
            "table_rows": len(table_rows),
            "index_rows": len(index_rows),
            "query_rows_seen": len(query_rows),
            "query_rows_stored": len(derived_queries),
            "events_created": len(events),
            "collector_ms": collector_ms,
            "notes": notes,
        }
        insert_collection_cycle(repo, instance_id, metrics)
        repo.commit()

        return {
            **metrics,
            "server_major": major,
            "pg_stat_statements": pgss_available,
        }


def run_forever(cfg: AgentConfig) -> None:
    LOG.info(
        "Starting PG Intelligence agent for %s; fast=%ss slow=%ss sizes=%ss budget=%.1fs text=%s",
        cfg.instance_name,
        cfg.interval_seconds,
        cfg.slow_interval_seconds,
        cfg.size_interval_seconds,
        cfg.max_source_cycle_seconds,
        cfg.query_text_mode,
    )
    last_slow = time.monotonic()
    last_size = last_slow
    while True:
        started = time.monotonic()
        now = started
        slow_due = (now - last_slow) >= cfg.slow_interval_seconds
        size_due = (now - last_size) >= cfg.size_interval_seconds
        try:
            result = collect_once(cfg, collect_slow=slow_due, collect_sizes=size_due)
            LOG.info(
                "Collected PG%d: db=%d tables=%d indexes=%d queries=%d/%d events=%d source=%.1fms cycle=%.1fms budget_exceeded=%s",
                result["server_major"], result["database_rows"], result["table_rows"], result["index_rows"],
                result["query_rows_stored"], result["query_rows_seen"], result["events_created"],
                result["source_duration_ms"], result["cycle_duration_ms"], result["budget_exceeded"],
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            LOG.exception("Collection cycle failed")
        finally:
            # A due slow/size cycle is not retried every minute if it was skipped
            # because the source budget was exceeded. This is intentionally conservative.
            if slow_due:
                last_slow = now
            if size_due:
                last_size = now
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, cfg.interval_seconds - elapsed))
