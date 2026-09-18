from __future__ import annotations

from datetime import timedelta

from .util import human_bytes


def text_report(conn, instance_name: str, hours: int = 24) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, last_seen_at, server_version FROM pgintel.instances WHERE name = %s", (instance_name,))
        inst = cur.fetchone()
        if not inst:
            raise ValueError(f"Unknown instance: {instance_name}")
        iid = inst["id"]

        cur.execute(
            """
            SELECT
                COALESCE(sum(xact_commit_delta + xact_rollback_delta),0) AS tx,
                COALESCE(sum(temp_bytes_delta),0) AS temp_bytes,
                COALESCE(sum(deadlocks_delta),0) AS deadlocks
            FROM pgintel.database_samples
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            """,
            (iid, hours),
        )
        db = cur.fetchone()

        cur.execute(
            """
            SELECT queryid, sum(calls_delta) calls, sum(total_exec_time_delta) total_ms,
                   CASE WHEN sum(calls_delta)>0 THEN sum(total_exec_time_delta)/sum(calls_delta) END mean_ms
            FROM pgintel.query_samples
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            GROUP BY queryid
            HAVING sum(calls_delta) > 0
            ORDER BY total_ms DESC
            LIMIT 10
            """,
            (iid, hours),
        )
        top = cur.fetchall()

        cur.execute(
            """
            SELECT created_at, severity, event_type, title
            FROM pgintel.events
            WHERE instance_id=%s AND created_at >= now() - (%s * interval '1 hour')
            ORDER BY created_at DESC
            LIMIT 20
            """,
            (iid, hours),
        )
        events = cur.fetchall()

    lines = [
        "PG Intelligence 0.1 - Report",
        f"Instance : {inst['name']}",
        f"Version  : {inst['server_version']}",
        f"Window   : last {hours} hour(s)",
        "",
        "WORKLOAD",
        f"  Transactions : {int(db['tx']):,}",
        f"  Temp written : {human_bytes(db['temp_bytes'])}",
        f"  Deadlocks    : {int(db['deadlocks'])}",
        "",
        "TOP QUERIES BY EXECUTION TIME",
    ]
    if top:
        for r in top:
            lines.append(
                f"  queryid={r['queryid']} calls={int(r['calls']):,} total={float(r['total_ms'])/1000:.2f}s mean={float(r['mean_ms']):.2f}ms"
            )
    else:
        lines.append("  (no query delta data yet; the first sample establishes the baseline)")

    lines.extend(["", "RECENT EVENTS"])
    if events:
        for e in events:
            lines.append(f"  {e['created_at']} [{e['severity'].upper()}] {e['title']}")
    else:
        lines.append("  No events in this window.")
    return "\n".join(lines)
