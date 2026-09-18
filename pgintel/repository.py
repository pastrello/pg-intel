from __future__ import annotations

from decimal import Decimal
from typing import Any

from .util import delta, pct, sha256_text


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


def insert_server_sample(conn, instance_id: int, sample: dict[str, Any]) -> None:
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO pgintel.server_samples
                (instance_id, collected_at, connections, active_connections, waiting_connections)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (
                instance_id,
                sample["collected_at"],
                sample["connections"],
                sample["active_connections"],
                sample["waiting_connections"],
            ),
        )


def _last_row(conn, table: str, instance_id: int, key_sql: str, key_values: tuple[Any, ...]):
    allowed = {"database_samples", "table_samples", "index_samples", "query_samples"}
    if table not in allowed:
        raise ValueError("invalid table")
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT * FROM pgintel.{table} WHERE instance_id = %s AND {key_sql} ORDER BY collected_at DESC LIMIT 1",
            (instance_id, *key_values),
        )
        return cur.fetchone()


def insert_database_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derived: list[dict[str, Any]] = []
    for row in rows:
        prev = _last_row(conn, "database_samples", instance_id, "datid = %s", (row["datid"],))
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

        with conn.cursor() as cur:
            cur.execute(
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
                {**row, **values, "instance_id": instance_id, "collected_at": collected_at},
            )
        derived.append({**row, **values})
    return derived


def insert_table_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derived = []
    for row in rows:
        prev = _last_row(conn, "table_samples", instance_id, "relid = %s", (row["relid"],))
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
        with conn.cursor() as cur:
            cur.execute(
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
                {**row, **vals, "instance_id": instance_id, "collected_at": collected_at},
            )
        derived.append({**row, **vals})
    return derived


def insert_index_samples(conn, instance_id: int, collected_at, rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    derived = []
    for row in rows:
        prev = _last_row(conn, "index_samples", instance_id, "indexrelid = %s", (row["indexrelid"],))
        vals = {"idx_scan_delta": int(delta(row["idx_scan"] or 0, prev["idx_scan_raw"] if prev else None))}
        with conn.cursor() as cur:
            cur.execute(
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
                {**row, **vals, "instance_id": instance_id, "collected_at": collected_at},
            )
        derived.append({**row, **vals})
    return derived


def insert_query_samples(
    conn,
    instance_id: int,
    collected_at,
    rows: list[dict[str, Any]],
    *,
    store_query_text: bool,
) -> list[dict[str, Any]]:
    derived = []
    for row in rows:
        prev = _last_row(
            conn,
            "query_samples",
            instance_id,
            "dbid = %s AND userid = %s AND queryid = %s",
            (row["dbid"], row["userid"], row["queryid"]),
        )

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
        vals["query_hash"] = sha256_text(row.get("query"))
        vals["query_text"] = row.get("query") if store_query_text else None

        with conn.cursor() as cur:
            cur.execute(
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
                {**row, **vals, "instance_id": instance_id, "collected_at": collected_at},
            )
        derived.append({**row, **vals})
    return derived


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
