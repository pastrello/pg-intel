from __future__ import annotations

import json
from typing import Any

from .util import delta, pct, sha256_text


COLLECTION_CYCLES_TABLE_DDL = """
CREATE TABLE IF NOT EXISTS pgintel.collection_cycles (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    cycle_duration_ms   double precision NOT NULL,
    source_duration_ms  double precision NOT NULL,
    repository_duration_ms double precision NOT NULL,
    slow_requested      boolean NOT NULL DEFAULT false,
    slow_collected      boolean NOT NULL DEFAULT false,
    sizes_requested     boolean NOT NULL DEFAULT false,
    sizes_collected     boolean NOT NULL DEFAULT false,
    budget_exceeded     boolean NOT NULL DEFAULT false,
    database_rows       integer NOT NULL DEFAULT 0,
    table_rows          integer NOT NULL DEFAULT 0,
    table_rows_stored   integer NOT NULL DEFAULT 0,
    index_rows          integer NOT NULL DEFAULT 0,
    index_rows_stored   integer NOT NULL DEFAULT 0,
    query_rows_seen     integer NOT NULL DEFAULT 0,
    query_rows_stored   integer NOT NULL DEFAULT 0,
    events_created      integer NOT NULL DEFAULT 0,
    events_suppressed   integer NOT NULL DEFAULT 0,
    collector_ms        jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes               jsonb NOT NULL DEFAULT '{}'::jsonb
);
"""
COLLECTION_CYCLES_INDEX_DDL = """
CREATE INDEX IF NOT EXISTS collection_cycles_instance_time_idx
    ON pgintel.collection_cycles(instance_id, collected_at DESC)
"""

REPOSITORY_EFFICIENCY_MIGRATION_DDL = """
ALTER TABLE pgintel.collection_cycles
    ADD COLUMN IF NOT EXISTS table_rows_stored integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS index_rows_stored integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS events_suppressed integer NOT NULL DEFAULT 0
"""


def ensure_instance(conn, name: str, server: dict[str, Any]) -> int:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pgintel.instances
                (name, last_seen_at, server_version, server_version_num, postmaster_start_time)
            VALUES (%s, now(), %s, %s, %s)
            ON CONFLICT (name) DO UPDATE SET
                last_seen_at = EXCLUDED.last_seen_at,
                server_version = EXCLUDED.server_version,
                server_version_num = EXCLUDED.server_version_num,
                postmaster_start_time = EXCLUDED.postmaster_start_time
            RETURNING id
            """,
            (name, server["server_version"], server["server_version_num"], server["postmaster_start_time"]),
        )
        return int(cur.fetchone()["id"])


def repository_schema_info(conn) -> dict[str, bool]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                to_regclass('pgintel.instances') IS NOT NULL AS core,
                to_regclass('pgintel.collection_cycles') IS NOT NULL AS production_safety,
                (
                    SELECT count(*) = 3
                    FROM information_schema.columns
                    WHERE table_schema = 'pgintel'
                      AND table_name = 'collection_cycles'
                      AND column_name IN ('table_rows_stored', 'index_rows_stored', 'events_suppressed')
                ) AS repository_efficiency
            """
        )
        row = cur.fetchone()
        return {
            "core": bool(row["core"]),
            "production_safety": bool(row["production_safety"]),
            "repository_efficiency": bool(row["repository_efficiency"]),
        }


def migrate_repository(conn) -> None:
    with conn.cursor() as cur:
        cur.execute(COLLECTION_CYCLES_TABLE_DDL)
        cur.execute(COLLECTION_CYCLES_INDEX_DDL)
        cur.execute(REPOSITORY_EFFICIENCY_MIGRATION_DDL)
    conn.commit()


def insert_server_sample(conn, instance_id: int, sample: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pgintel.server_samples
                (instance_id, collected_at, connections, active_connections, waiting_connections)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                instance_id, sample["collected_at"], sample["connections"],
                sample["active_connections"], sample["waiting_connections"],
            ),
        )


def _latest_rows(
    conn,
    table: str,
    instance_id: int,
    key_columns: tuple[str, ...],
    keys: list[tuple[Any, ...]],
) -> dict[tuple[Any, ...], dict[str, Any]]:
    allowed_keys = {
        "database_samples": ("datid",),
        "table_samples": ("relid",),
        "index_samples": ("indexrelid",),
        "query_samples": ("dbid", "userid", "queryid"),
    }
    if allowed_keys.get(table) != key_columns:
        raise ValueError("invalid latest-row lookup")
    if not keys:
        return {}

    with conn.cursor() as cur:
        if len(key_columns) == 1:
            column = key_columns[0]
            values = [key[0] for key in keys]
            cur.execute(
                f"""
                SELECT DISTINCT ON ({column}) *
                FROM pgintel.{table}
                WHERE instance_id = %s
                  AND {column} = ANY(%s::oid[])
                ORDER BY {column}, collected_at DESC
                """,
                (instance_id, values),
            )
        else:
            dbids = [key[0] for key in keys]
            userids = [key[1] for key in keys]
            queryids = [key[2] for key in keys]
            cur.execute(
                """
                WITH wanted(dbid, userid, queryid) AS (
                    SELECT *
                    FROM unnest(%s::oid[], %s::oid[], %s::bigint[])
                )
                SELECT DISTINCT ON (q.dbid, q.userid, q.queryid) q.*
                FROM pgintel.query_samples q
                JOIN wanted w
                  ON w.dbid = q.dbid
                 AND w.userid = q.userid
                 AND w.queryid = q.queryid
                WHERE q.instance_id = %s
                ORDER BY q.dbid, q.userid, q.queryid, q.collected_at DESC
                """,
                (dbids, userids, queryids, instance_id),
            )
        rows = cur.fetchall()
    return {tuple(row[column] for column in key_columns): row for row in rows}


def insert_database_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = _latest_rows(
        conn, "database_samples", instance_id, ("datid",),
        [(row["datid"],) for row in rows],
    )
    derived: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row in rows:
        prev = previous.get((row["datid"],))
        reset_changed = bool(prev and row["stats_reset"] != prev["stats_reset"])

        def d(raw_key: str, prev_col: str):
            if reset_changed:
                return row[raw_key]
            return delta(row[raw_key], prev[prev_col] if prev else None)

        values = {
            "xact_commit_delta": int(d("xact_commit", "xact_commit_raw")),
            "xact_rollback_delta": int(d("xact_rollback", "xact_rollback_raw")),
            "blks_read_delta": int(d("blks_read", "blks_read_raw")),
            "blks_hit_delta": int(d("blks_hit", "blks_hit_raw")),
            "temp_files_delta": int(d("temp_files", "temp_files_raw")),
            "temp_bytes_delta": int(d("temp_bytes", "temp_bytes_raw")),
            "deadlocks_delta": int(d("deadlocks", "deadlocks_raw")),
        }
        values["cache_hit_ratio"] = pct(
            values["blks_hit_delta"], values["blks_hit_delta"] + values["blks_read_delta"]
        )
        size = row.get("database_size_bytes")
        if size is None and prev:
            size = prev["database_size_bytes"]
        materialized = {**row, **values, "database_size_bytes": size}
        derived.append(materialized)
        payloads.append({**materialized, "instance_id": instance_id, "collected_at": collected_at})

    if payloads:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pgintel.database_samples (
                    instance_id, collected_at, datid, datname, numbackends, database_size_bytes, stats_reset,
                    xact_commit_raw, xact_rollback_raw, blks_read_raw, blks_hit_raw,
                    temp_files_raw, temp_bytes_raw, deadlocks_raw,
                    xact_commit_delta, xact_rollback_delta, blks_read_delta, blks_hit_delta,
                    temp_files_delta, temp_bytes_delta, deadlocks_delta, cache_hit_ratio
                ) VALUES (
                    %(instance_id)s, %(collected_at)s, %(datid)s, %(datname)s, %(numbackends)s,
                    %(database_size_bytes)s, %(stats_reset)s,
                    %(xact_commit)s, %(xact_rollback)s, %(blks_read)s, %(blks_hit)s,
                    %(temp_files)s, %(temp_bytes)s, %(deadlocks)s,
                    %(xact_commit_delta)s, %(xact_rollback_delta)s, %(blks_read_delta)s, %(blks_hit_delta)s,
                    %(temp_files_delta)s, %(temp_bytes_delta)s, %(deadlocks_delta)s, %(cache_hit_ratio)s
                )
                """,
                payloads,
            )
    return derived


def insert_table_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = _latest_rows(
        conn, "table_samples", instance_id, ("relid",),
        [(row["relid"],) for row in rows],
    )
    derived: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row in rows:
        prev = previous.get((row["relid"],))
        vals = {
            "seq_scan_delta": int(delta(row["seq_scan"], prev["seq_scan_raw"] if prev else None)),
            "idx_scan_delta": int(delta(row["idx_scan"] or 0, prev["idx_scan_raw"] if prev else None)),
            "n_tup_ins_delta": int(delta(row["n_tup_ins"], prev["n_tup_ins_raw"] if prev else None)),
            "n_tup_upd_delta": int(delta(row["n_tup_upd"], prev["n_tup_upd_raw"] if prev else None)),
            "n_tup_del_delta": int(delta(row["n_tup_del"], prev["n_tup_del_raw"] if prev else None)),
        }
        live = int(row["n_live_tup"] or 0)
        dead = int(row["n_dead_tup"] or 0)
        vals["dead_tuple_ratio"] = pct(dead, live + dead)
        size = row.get("total_size_bytes")
        if size is None and prev:
            size = prev["total_size_bytes"]
        materialized = {**row, **vals, "total_size_bytes": size}

        changed = prev is None or any((
            row["seq_scan"] != prev["seq_scan_raw"],
            (row["idx_scan"] or 0) != (prev["idx_scan_raw"] or 0),
            row["n_tup_ins"] != prev["n_tup_ins_raw"],
            row["n_tup_upd"] != prev["n_tup_upd_raw"],
            row["n_tup_del"] != prev["n_tup_del_raw"],
            live != int(prev["n_live_tup"] or 0),
            dead != int(prev["n_dead_tup"] or 0),
            row["n_mod_since_analyze"] != prev["n_mod_since_analyze"],
            row["last_vacuum"] != prev["last_vacuum"],
            row["last_autovacuum"] != prev["last_autovacuum"],
            row["last_analyze"] != prev["last_analyze"],
            row["last_autoanalyze"] != prev["last_autoanalyze"],
            size != prev["total_size_bytes"],
        ))
        if not changed:
            continue

        derived.append(materialized)
        payloads.append({**materialized, "instance_id": instance_id, "collected_at": collected_at})

    if payloads:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pgintel.table_samples (
                    instance_id, collected_at, relid, schemaname, relname, total_size_bytes,
                    seq_scan_raw, idx_scan_raw, n_tup_ins_raw, n_tup_upd_raw, n_tup_del_raw,
                    seq_scan_delta, idx_scan_delta, n_tup_ins_delta, n_tup_upd_delta, n_tup_del_delta,
                    n_live_tup, n_dead_tup, dead_tuple_ratio, n_mod_since_analyze,
                    last_vacuum, last_autovacuum, last_analyze, last_autoanalyze
                ) VALUES (
                    %(instance_id)s, %(collected_at)s, %(relid)s, %(schemaname)s, %(relname)s, %(total_size_bytes)s,
                    %(seq_scan)s, %(idx_scan)s, %(n_tup_ins)s, %(n_tup_upd)s, %(n_tup_del)s,
                    %(seq_scan_delta)s, %(idx_scan_delta)s, %(n_tup_ins_delta)s, %(n_tup_upd_delta)s, %(n_tup_del_delta)s,
                    %(n_live_tup)s, %(n_dead_tup)s, %(dead_tuple_ratio)s, %(n_mod_since_analyze)s,
                    %(last_vacuum)s, %(last_autovacuum)s, %(last_analyze)s, %(last_autoanalyze)s
                )
                """,
                payloads,
            )
    return derived


def insert_index_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    previous = _latest_rows(
        conn, "index_samples", instance_id, ("indexrelid",),
        [(row["indexrelid"],) for row in rows],
    )
    derived: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row in rows:
        prev = previous.get((row["indexrelid"],))
        idx_scan = int(row["idx_scan"] or 0)
        vals = {"idx_scan_delta": int(delta(idx_scan, prev["idx_scan_raw"] if prev else None))}
        size = row.get("index_size_bytes")
        if size is None and prev:
            size = prev["index_size_bytes"]
        materialized = {**row, **vals, "index_size_bytes": size}

        changed = prev is None or any((
            idx_scan != int(prev["idx_scan_raw"] or 0),
            row["idx_tup_read"] != prev["idx_tup_read_raw"],
            row["idx_tup_fetch"] != prev["idx_tup_fetch_raw"],
            size != prev["index_size_bytes"],
            row["indisunique"] != prev["indisunique"],
            row["indisprimary"] != prev["indisprimary"],
            row["indisvalid"] != prev["indisvalid"],
        ))
        if not changed:
            continue

        derived.append(materialized)
        payloads.append({**materialized, "instance_id": instance_id, "collected_at": collected_at})

    if payloads:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pgintel.index_samples (
                    instance_id, collected_at, indexrelid, relid, schemaname, relname, indexrelname,
                    index_size_bytes, idx_scan_raw, idx_scan_delta, idx_tup_read_raw, idx_tup_fetch_raw,
                    indisunique, indisprimary, indisvalid
                ) VALUES (
                    %(instance_id)s, %(collected_at)s, %(indexrelid)s, %(relid)s, %(schemaname)s, %(relname)s,
                    %(indexrelname)s, %(index_size_bytes)s, %(idx_scan)s, %(idx_scan_delta)s,
                    %(idx_tup_read)s, %(idx_tup_fetch)s, %(indisunique)s, %(indisprimary)s, %(indisvalid)s
                )
                """,
                payloads,
            )
    return derived


def insert_query_samples(
    conn,
    instance_id: int,
    collected_at,
    rows: list[dict[str, Any]],
    *,
    store_query_text: bool,
) -> list[dict[str, Any]]:
    previous = _latest_rows(
        conn, "query_samples", instance_id, ("dbid", "userid", "queryid"),
        [(row["dbid"], row["userid"], row["queryid"]) for row in rows],
    )
    derived: list[dict[str, Any]] = []
    payloads: list[dict[str, Any]] = []
    for row in rows:
        prev = previous.get((row["dbid"], row["userid"], row["queryid"]))

        def d(raw_key: str, prev_col: str):
            return delta(row[raw_key] or 0, prev[prev_col] if prev else None)

        vals = {
            "plans_delta": int(d("plans", "plans_raw")),
            "calls_delta": int(d("calls", "calls_raw")),
            "total_plan_time_delta": float(d("total_plan_time", "total_plan_time_raw")),
            "total_exec_time_delta": float(d("total_exec_time", "total_exec_time_raw")),
            "rows_delta": int(d("rows", "rows_raw")),
            "shared_blks_hit_delta": int(d("shared_blks_hit", "shared_blks_hit_raw")),
            "shared_blks_read_delta": int(d("shared_blks_read", "shared_blks_read_raw")),
            "temp_blks_read_delta": int(d("temp_blks_read", "temp_blks_read_raw")),
            "temp_blks_written_delta": int(d("temp_blks_written", "temp_blks_written_raw")),
            "wal_bytes_delta": d("wal_bytes", "wal_bytes_raw"),
        }
        vals["mean_exec_time_ms"] = (
            vals["total_exec_time_delta"] / vals["calls_delta"] if vals["calls_delta"] > 0 else None
        )

        if prev is not None and vals["calls_delta"] == 0 and vals["plans_delta"] == 0:
            continue

        query = row.get("query")
        vals["query_hash"] = sha256_text(query) if query else (prev["query_hash"] if prev else None)
        vals["query_text"] = query if store_query_text else None
        materialized = {**row, **vals}
        derived.append(materialized)
        payloads.append({**materialized, "instance_id": instance_id, "collected_at": collected_at})

    if payloads:
        with conn.cursor() as cur:
            cur.executemany(
                """
                INSERT INTO pgintel.query_samples (
                    instance_id, collected_at, dbid, userid, queryid, toplevel, query_hash, query_text,
                    plans_raw, calls_raw, total_plan_time_raw, total_exec_time_raw, rows_raw,
                    shared_blks_hit_raw, shared_blks_read_raw, temp_blks_read_raw, temp_blks_written_raw, wal_bytes_raw,
                    plans_delta, calls_delta, total_plan_time_delta, total_exec_time_delta, rows_delta,
                    shared_blks_hit_delta, shared_blks_read_delta, temp_blks_read_delta, temp_blks_written_delta,
                    wal_bytes_delta, mean_exec_time_ms
                ) VALUES (
                    %(instance_id)s, %(collected_at)s, %(dbid)s, %(userid)s, %(queryid)s, %(toplevel)s,
                    %(query_hash)s, %(query_text)s,
                    %(plans)s, %(calls)s, %(total_plan_time)s, %(total_exec_time)s, %(rows)s,
                    %(shared_blks_hit)s, %(shared_blks_read)s, %(temp_blks_read)s, %(temp_blks_written)s, %(wal_bytes)s,
                    %(plans_delta)s, %(calls_delta)s, %(total_plan_time_delta)s, %(total_exec_time_delta)s, %(rows_delta)s,
                    %(shared_blks_hit_delta)s, %(shared_blks_read_delta)s, %(temp_blks_read_delta)s,
                    %(temp_blks_written_delta)s, %(wal_bytes_delta)s, %(mean_exec_time_ms)s
                )
                """,
                payloads,
            )
    return derived


def update_query_texts(conn, instance_id: int, collected_at, texts: dict[tuple[int, int, int], str]) -> int:
    updated = 0
    with conn.cursor() as cur:
        for (dbid, userid, queryid), query in texts.items():
            cur.execute(
                """
                UPDATE pgintel.query_samples
                   SET query_text = %s, query_hash = %s
                 WHERE instance_id = %s AND collected_at = %s
                   AND dbid = %s AND userid = %s AND queryid = %s
                """,
                (query, sha256_text(query), instance_id, collected_at, dbid, userid, queryid),
            )
            updated += cur.rowcount
    return updated


def insert_collection_cycle(conn, instance_id: int, metrics: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pgintel.collection_cycles (
                instance_id, collected_at, cycle_duration_ms, source_duration_ms, repository_duration_ms,
                slow_requested, slow_collected, sizes_requested, sizes_collected, budget_exceeded,
                database_rows, table_rows, table_rows_stored, index_rows, index_rows_stored,
                query_rows_seen, query_rows_stored, events_created, events_suppressed,
                collector_ms, notes
            ) VALUES (
                %(instance_id)s, %(collected_at)s, %(cycle_duration_ms)s, %(source_duration_ms)s,
                %(repository_duration_ms)s, %(slow_requested)s, %(slow_collected)s, %(sizes_requested)s,
                %(sizes_collected)s, %(budget_exceeded)s, %(database_rows)s, %(table_rows)s,
                %(table_rows_stored)s, %(index_rows)s, %(index_rows_stored)s,
                %(query_rows_seen)s, %(query_rows_stored)s, %(events_created)s, %(events_suppressed)s,
                %(collector_ms)s::jsonb, %(notes)s::jsonb
            )
            """,
            {
                **metrics,
                "collector_ms": json.dumps(metrics.get("collector_ms", {})),
                "notes": json.dumps(metrics.get("notes", {})),
            },
        )


def insert_event(conn, instance_id: int, severity: str, event_type: str, object_type: str | None,
                 object_key: str | None, title: str, details_json: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pgintel.events
                (instance_id, severity, event_type, object_type, object_key, title, details)
            VALUES (%s, %s, %s, %s, %s, %s, %s::jsonb)
            """,
            (instance_id, severity, event_type, object_type, object_key, title, details_json),
        )
