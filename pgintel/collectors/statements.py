from __future__ import annotations

from typing import Iterable


_REQUIRED_COLUMNS = {
    "dbid", "userid", "queryid", "calls", "total_exec_time", "rows",
    "shared_blks_hit", "shared_blks_read", "temp_blks_read", "temp_blks_written",
}


def extension_available(conn) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_stat_statements') AS ok")
        return bool(cur.fetchone()["ok"])


def available_columns(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass('pg_stat_statements')
              AND a.attnum > 0
              AND NOT a.attisdropped
            """
        )
        return {row["attname"] for row in cur.fetchall()}


def _expr(columns: set[str], preferred: str, alias: str, *, fallback: str | None = None,
          default_sql: str = "0") -> str:
    if preferred in columns:
        return f"s.{preferred} AS {alias}"
    if fallback and fallback in columns:
        return f"s.{fallback} AS {alias}"
    return f"{default_sql} AS {alias}"


def _build_select(columns: Iterable[str], *, include_query_text: bool = False) -> str:
    columns = set(columns)
    missing = sorted(_REQUIRED_COLUMNS - columns)
    if missing:
        raise RuntimeError("pg_stat_statements is missing required columns: " + ", ".join(missing))

    shared_read = _expr(
        columns, "shared_blk_read_time", "blk_read_time", fallback="blk_read_time",
        default_sql="0::double precision",
    )
    shared_write = _expr(
        columns, "shared_blk_write_time", "blk_write_time", fallback="blk_write_time",
        default_sql="0::double precision",
    )
    optional = {
        "toplevel": _expr(columns, "toplevel", "toplevel", default_sql="true"),
        "plans": _expr(columns, "plans", "plans", default_sql="0::bigint"),
        "total_plan_time": _expr(columns, "total_plan_time", "total_plan_time", default_sql="0::double precision"),
        "shared_blks_dirtied": _expr(columns, "shared_blks_dirtied", "shared_blks_dirtied", default_sql="0::bigint"),
        "shared_blks_written": _expr(columns, "shared_blks_written", "shared_blks_written", default_sql="0::bigint"),
        "local_blks_hit": _expr(columns, "local_blks_hit", "local_blks_hit", default_sql="0::bigint"),
        "local_blks_read": _expr(columns, "local_blks_read", "local_blks_read", default_sql="0::bigint"),
        "temp_blk_read_time": _expr(columns, "temp_blk_read_time", "temp_blk_read_time", default_sql="0::double precision"),
        "temp_blk_write_time": _expr(columns, "temp_blk_write_time", "temp_blk_write_time", default_sql="0::double precision"),
        "wal_records": _expr(columns, "wal_records", "wal_records", default_sql="0::bigint"),
        "wal_fpi": _expr(columns, "wal_fpi", "wal_fpi", default_sql="0::bigint"),
        "wal_bytes": _expr(columns, "wal_bytes", "wal_bytes", default_sql="0::numeric"),
        "jit_functions": _expr(columns, "jit_functions", "jit_functions", default_sql="0::bigint"),
        "jit_generation_time": _expr(columns, "jit_generation_time", "jit_generation_time", default_sql="0::double precision"),
    }
    query_expr = "s.query" if include_query_text else "NULL::text"
    source = "pg_stat_statements(true)" if include_query_text else "pg_stat_statements(false)"

    return f"""
        SELECT
            s.dbid,
            s.userid,
            s.queryid,
            {optional['toplevel']},
            {query_expr} AS query,
            {optional['plans']},
            {optional['total_plan_time']},
            s.calls,
            s.total_exec_time,
            s.rows,
            s.shared_blks_hit,
            s.shared_blks_read,
            {optional['shared_blks_dirtied']},
            {optional['shared_blks_written']},
            {optional['local_blks_hit']},
            {optional['local_blks_read']},
            s.temp_blks_read,
            s.temp_blks_written,
            {shared_read},
            {shared_write},
            {optional['temp_blk_read_time']},
            {optional['temp_blk_write_time']},
            {optional['wal_records']},
            {optional['wal_fpi']},
            {optional['wal_bytes']},
            {optional['jit_functions']},
            {optional['jit_generation_time']}
        FROM {source} AS s
        WHERE s.queryid IS NOT NULL
          AND s.dbid = (
              SELECT oid
              FROM pg_database
              WHERE datname = current_database()
          )
    """


def compatibility_info(conn) -> dict:
    columns = available_columns(conn)
    missing = sorted(_REQUIRED_COLUMNS - columns)
    if "shared_blk_read_time" in columns:
        io_timing_layout = "postgresql_17_plus"
    elif "blk_read_time" in columns:
        io_timing_layout = "postgresql_16_or_older"
    else:
        io_timing_layout = "timing_columns_unavailable"
    return {
        "compatible": not missing,
        "missing_required_columns": missing,
        "io_timing_layout": io_timing_layout,
        "column_count": len(columns),
    }


def collect(conn, *, include_query_text: bool = False):
    columns = available_columns(conn)
    sql = _build_select(columns, include_query_text=include_query_text)
    with conn.cursor() as cur:
        cur.execute(sql)
        return cur.fetchall()


def fetch_query_texts(conn, keys: set[tuple[int, int, int]]) -> dict[tuple[int, int, int], str]:
    if not keys:
        return {}
    clauses = []
    params: list[int] = []
    for dbid, userid, queryid in sorted(keys):
        clauses.append("(s.dbid=%s AND s.userid=%s AND s.queryid=%s)")
        params.extend((dbid, userid, queryid))
    sql = f"""
        SELECT s.dbid, s.userid, s.queryid, s.query
        FROM pg_stat_statements(true) AS s
        WHERE {' OR '.join(clauses)}
    """
    with conn.cursor() as cur:
        cur.execute(sql, tuple(params))
        return {
            (int(row["dbid"]), int(row["userid"]), int(row["queryid"])): row["query"]
            for row in cur.fetchall()
            if row.get("query")
        }
