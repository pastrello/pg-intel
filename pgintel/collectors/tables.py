from __future__ import annotations


def collect(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                s.relid,
                s.schemaname,
                s.relname,
                s.seq_scan,
                s.seq_tup_read,
                s.idx_scan,
                s.idx_tup_fetch,
                s.n_tup_ins,
                s.n_tup_upd,
                s.n_tup_del,
                s.n_tup_hot_upd,
                s.n_live_tup,
                s.n_dead_tup,
                s.n_mod_since_analyze,
                s.last_vacuum,
                s.last_autovacuum,
                s.last_analyze,
                s.last_autoanalyze,
                s.vacuum_count,
                s.autovacuum_count,
                s.analyze_count,
                s.autoanalyze_count,
                pg_total_relation_size(s.relid) AS total_size_bytes
            FROM pg_stat_user_tables s
            ORDER BY s.schemaname, s.relname
            """
        )
        return cur.fetchall()
