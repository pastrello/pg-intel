from __future__ import annotations


def collect(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                i.relid,
                i.indexrelid,
                i.schemaname,
                i.relname,
                i.indexrelname,
                i.idx_scan,
                i.idx_tup_read,
                i.idx_tup_fetch,
                pg_relation_size(i.indexrelid) AS index_size_bytes,
                ix.indisunique,
                ix.indisprimary,
                ix.indisvalid
            FROM pg_stat_user_indexes i
            JOIN pg_index ix ON ix.indexrelid = i.indexrelid
            ORDER BY i.schemaname, i.relname, i.indexrelname
            """
        )
        return cur.fetchall()
