from __future__ import annotations


_REQUIRED_COLUMNS = {
    "datid", "datname", "numbackends", "xact_commit", "xact_rollback", "blks_read", "blks_hit",
    "tup_returned", "tup_fetched", "tup_inserted", "tup_updated", "tup_deleted", "conflicts",
    "temp_files", "temp_bytes", "deadlocks", "blk_read_time", "blk_write_time", "stats_reset",
}

_OPTIONAL_COLUMNS = {
    # PostgreSQL 14+
    "session_time": "0::double precision",
    "active_time": "0::double precision",
    "idle_in_transaction_time": "0::double precision",
    "sessions": "0::bigint",
    "sessions_abandoned": "0::bigint",
    "sessions_fatal": "0::bigint",
    "sessions_killed": "0::bigint",
    # PostgreSQL 18+
    "parallel_workers_to_launch": "0::bigint",
    "parallel_workers_launched": "0::bigint",
}


def available_columns(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass('pg_stat_database')
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
        return {row["attname"] for row in cur.fetchall()}


def compatibility_info(conn) -> dict:
    columns = available_columns(conn)
    missing = sorted(_REQUIRED_COLUMNS - columns)
    return {
        "compatible": not missing,
        "missing_required_columns": missing,
        "session_statistics": all(c in columns for c in (
            "session_time", "active_time", "idle_in_transaction_time", "sessions",
            "sessions_abandoned", "sessions_fatal", "sessions_killed",
        )),
        "parallel_worker_statistics": all(c in columns for c in (
            "parallel_workers_to_launch", "parallel_workers_launched",
        )),
        "column_count": len(columns),
    }


def _expr(columns: set[str], name: str) -> str:
    if name in columns:
        return f"d.{name} AS {name}"
    return f"{_OPTIONAL_COLUMNS[name]} AS {name}"


def _build_select(columns: set[str]) -> str:
    missing = sorted(_REQUIRED_COLUMNS - columns)
    if missing:
        raise RuntimeError("pg_stat_database is missing required columns: " + ", ".join(missing))
    optional = ",\n                ".join(_expr(columns, name) for name in _OPTIONAL_COLUMNS)
    return f"""
            SELECT
                d.datid,
                d.datname,
                d.numbackends,
                d.xact_commit,
                d.xact_rollback,
                d.blks_read,
                d.blks_hit,
                d.tup_returned,
                d.tup_fetched,
                d.tup_inserted,
                d.tup_updated,
                d.tup_deleted,
                d.conflicts,
                d.temp_files,
                d.temp_bytes,
                d.deadlocks,
                d.blk_read_time,
                d.blk_write_time,
                {optional},
                d.stats_reset,
                pg_database_size(d.datid) AS database_size_bytes
            FROM pg_stat_database d
            WHERE d.datname IS NOT NULL
            ORDER BY d.datname
            """


def collect(conn):
    columns = available_columns(conn)
    with conn.cursor() as cur:
        cur.execute(_build_select(columns))
        return cur.fetchall()
