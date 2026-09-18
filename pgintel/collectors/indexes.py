from __future__ import annotations


def _build_select(*, include_size: bool = False) -> str:
    size_expr = "pg_relation_size(i.indexrelid)" if include_size else "NULL::bigint"
    return f"""
            SELECT
                i.relid,
                i.indexrelid,
                i.schemaname,
                i.relname,
                i.indexrelname,
                i.idx_scan,
                i.idx_tup_read,
                i.idx_tup_fetch,
                {size_expr} AS index_size_bytes,
                ix.indisunique,
                ix.indisprimary,
                ix.indisvalid
            FROM pg_stat_user_indexes i
            JOIN pg_index ix ON ix.indexrelid = i.indexrelid
            ORDER BY i.schemaname, i.relname, i.indexrelname
            """


def collect(conn, *, include_size: bool = False):
    with conn.cursor() as cur:
        cur.execute(_build_select(include_size=include_size))
        return cur.fetchall()
