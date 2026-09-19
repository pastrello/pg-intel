from __future__ import annotations

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
            SELECT COALESCE(sum(xact_commit_delta + xact_rollback_delta),0) AS tx,
                   COALESCE(sum(temp_bytes_delta),0) AS temp_bytes,
                   COALESCE(sum(deadlocks_delta),0) AS deadlocks
            FROM pgintel.database_samples
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            """, (iid, hours),
        )
        db = cur.fetchone()

        cur.execute(
            """
            SELECT queryid, sum(calls_delta) calls, sum(total_exec_time_delta) total_ms,
                   CASE WHEN sum(calls_delta)>0 THEN sum(total_exec_time_delta)/sum(calls_delta) END mean_ms
            FROM pgintel.query_samples
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            GROUP BY queryid HAVING sum(calls_delta) > 0
            ORDER BY total_ms DESC LIMIT 10
            """, (iid, hours),
        )
        top = cur.fetchall()

        cur.execute(
            """
            SELECT created_at, severity, event_type, title
            FROM pgintel.events
            WHERE instance_id=%s AND created_at >= now() - (%s * interval '1 hour')
            ORDER BY created_at DESC LIMIT 20
            """, (iid, hours),
        )
        events = cur.fetchall()

    lines = [
        "PG Intelligence - Report",
        f"Instance : {inst['name']}",
        f"Version  : {inst['server_version']}",
        f"Window   : last {hours} hour(s)", "", "WORKLOAD",
        f"  Transactions : {int(db['tx']):,}",
        f"  Temp written : {human_bytes(db['temp_bytes'])}",
        f"  Deadlocks    : {int(db['deadlocks'])}", "", "TOP QUERIES BY EXECUTION TIME",
    ]
    if top:
        for r in top:
            lines.append(
                f"  queryid={r['queryid']} calls={int(r['calls']):,} "
                f"total={float(r['total_ms'])/1000:.2f}s mean={float(r['mean_ms']):.2f}ms"
            )
    else:
        lines.append("  (no query delta data yet)")
    lines.extend(["", "RECENT EVENTS"])
    if events:
        for e in events:
            lines.append(f"  {e['created_at']} [{e['severity'].upper()}] {e['title']}")
    else:
        lines.append("  No events in this window.")
    return "\n".join(lines)


def health_report(conn, instance_name: str, hours: int = 24) -> str:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name FROM pgintel.instances WHERE name=%s", (instance_name,))
        inst = cur.fetchone()
        if not inst:
            raise ValueError(f"Unknown instance: {instance_name}")
        iid = inst["id"]
        cur.execute(
            """
            SELECT
                count(*) AS cycles,
                avg(cycle_duration_ms) AS avg_cycle_ms,
                max(cycle_duration_ms) AS max_cycle_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY cycle_duration_ms) AS p95_cycle_ms,
                avg(source_duration_ms) AS avg_source_ms,
                max(source_duration_ms) AS max_source_ms,
                avg(repository_duration_ms) AS avg_repository_ms,
                sum(table_rows) AS table_rows_seen,
                sum(table_rows_stored) AS table_rows_stored,
                sum(index_rows) AS index_rows_seen,
                sum(index_rows_stored) AS index_rows_stored,
                sum(query_rows_seen) AS query_rows_seen,
                sum(query_rows_stored) AS query_rows_stored,
                sum(events_created) AS events_created,
                sum(events_suppressed) AS events_suppressed,
                count(*) FILTER (WHERE budget_exceeded) AS budget_exceeded_cycles,
                count(*) FILTER (WHERE slow_collected) AS slow_cycles,
                count(*) FILTER (WHERE sizes_collected) AS size_cycles
            FROM pgintel.collection_cycles
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            """,
            (iid, hours),
        )
        r = cur.fetchone()
        cur.execute(
            """
            SELECT
                CASE
                    WHEN sizes_collected THEN 'SIZE'
                    WHEN slow_collected THEN 'SLOW'
                    ELSE 'FAST'
                END AS cycle_class,
                count(*) AS cycles,
                avg(cycle_duration_ms) AS avg_cycle_ms,
                percentile_cont(0.95) WITHIN GROUP (ORDER BY cycle_duration_ms) AS p95_cycle_ms,
                max(cycle_duration_ms) AS max_cycle_ms,
                avg(source_duration_ms) AS avg_source_ms,
                avg(repository_duration_ms) AS avg_repository_ms
            FROM pgintel.collection_cycles
            WHERE instance_id=%s AND collected_at >= now() - (%s * interval '1 hour')
            GROUP BY 1
            """,
            (iid, hours),
        )
        classes = cur.fetchall()

    if not r["cycles"]:
        return (
            f"PG Intelligence - Collector Health\nInstance : {instance_name}\n"
            f"No collection cycles in the last {hours} hour(s)."
        )

    def reduction(seen_value, stored_value) -> float:
        seen = int(seen_value or 0)
        stored = int(stored_value or 0)
        return (1.0 - stored / seen) * 100.0 if seen else 0.0

    query_seen = int(r["query_rows_seen"] or 0)
    query_stored = int(r["query_rows_stored"] or 0)
    table_seen = int(r["table_rows_seen"] or 0)
    table_stored = int(r["table_rows_stored"] or 0)
    index_seen = int(r["index_rows_seen"] or 0)
    index_stored = int(r["index_rows_stored"] or 0)

    lines = [
        "PG Intelligence - Collector Health",
        f"Instance              : {instance_name}",
        f"Window                : last {hours} hour(s)",
        f"Cycles                : {int(r['cycles'])}",
        f"Cycle avg / p95 / max : {float(r['avg_cycle_ms']):.1f} / {float(r['p95_cycle_ms']):.1f} / {float(r['max_cycle_ms']):.1f} ms",
        f"Source avg / max      : {float(r['avg_source_ms']):.1f} / {float(r['max_source_ms']):.1f} ms",
        f"Repository avg        : {float(r['avg_repository_ms']):.1f} ms",
        f"Budget exceeded       : {int(r['budget_exceeded_cycles'])} cycle(s)",
        f"Slow / size cycles    : {int(r['slow_cycles'])} / {int(r['size_cycles'])}",
        f"Table rows seen/stored: {table_seen:,} / {table_stored:,} ({reduction(table_seen, table_stored):.1f}% reduction)",
        f"Index rows seen/stored: {index_seen:,} / {index_stored:,} ({reduction(index_seen, index_stored):.1f}% reduction)",
        f"Statements seen/stored: {query_seen:,} / {query_stored:,} ({reduction(query_seen, query_stored):.1f}% reduction)",
        f"Events created/suppressed: {int(r['events_created'] or 0):,} / {int(r['events_suppressed'] or 0):,}",
        "",
        "CYCLE CLASSES",
    ]

    order = {"FAST": 0, "SLOW": 1, "SIZE": 2}
    for row in sorted(classes, key=lambda item: order.get(item["cycle_class"], 99)):
        lines.append(
            f"  {row['cycle_class']:<4} cycles={int(row['cycles']):,} "
            f"cycle avg/p95/max={float(row['avg_cycle_ms']):.1f}/{float(row['p95_cycle_ms']):.1f}/{float(row['max_cycle_ms']):.1f}ms "
            f"source avg={float(row['avg_source_ms']):.1f}ms "
            f"repo avg={float(row['avg_repository_ms']):.1f}ms"
        )
    return "\n".join(lines)
