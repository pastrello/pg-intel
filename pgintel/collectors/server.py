from __future__ import annotations


def collect(conn):
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT
                current_setting('server_version') AS server_version,
                current_setting('server_version_num')::int AS server_version_num,
                pg_postmaster_start_time() AS postmaster_start_time,
                now() AS collected_at,
                (SELECT count(*) FROM pg_stat_activity) AS connections,
                (SELECT count(*) FROM pg_stat_activity WHERE state = 'active') AS active_connections,
                (SELECT count(*) FROM pg_stat_activity WHERE wait_event IS NOT NULL) AS waiting_connections
            """
        )
        return cur.fetchone()
