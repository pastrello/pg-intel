from __future__ import annotations


def collect(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
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
                d.session_time,
                d.active_time,
                d.idle_in_transaction_time,
                d.sessions,
                d.sessions_abandoned,
                d.sessions_fatal,
                d.sessions_killed,
                d.stats_reset,
                pg_database_size(d.datid) AS database_size_bytes
            FROM pg_stat_database d
            WHERE d.datname IS NOT NULL
            ORDER BY d.datname
            """
        )
        return cur.fetchall()
