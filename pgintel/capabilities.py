from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

MIN_SUPPORTED_MAJOR = 13
MAX_VALIDATED_MAJOR = 18
BASELINE_MAJOR = 18

# PostgreSQL community lifecycle dates (https://www.postgresql.org/support/versioning/).
# Kept as dates so the assessment remains useful without Internet access.
LIFECYCLE = {
    13: date(2025, 11, 13),
    14: date(2026, 11, 12),
    15: date(2027, 11, 11),
    16: date(2028, 11, 9),
    17: date(2029, 11, 8),
    18: date(2030, 11, 14),
}


@dataclass(frozen=True)
class CapabilitySpec:
    key: str
    label: str
    min_major: int
    source: str
    benefit: str
    required_relation: str | None = None
    required_columns: tuple[str, ...] = ()
    requires_pgss: bool = False
    category: str = "monitoring"


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    CapabilitySpec(
        "server_activity",
        "Server/session activity (pg_stat_activity)",
        13,
        "pg_stat_activity",
        "Connections, active sessions and wait-event visibility used by the core collector.",
        "pg_stat_activity",
        ("pid", "state", "wait_event", "query_start"),
    ),
    CapabilitySpec(
        "database_core",
        "Core database statistics (pg_stat_database)",
        13,
        "pg_stat_database",
        "Transactions, cache counters, temp usage, deadlocks and database size.",
        "pg_stat_database",
        ("datid", "datname", "xact_commit", "xact_rollback", "blks_read", "blks_hit", "temp_bytes", "deadlocks"),
    ),
    CapabilitySpec(
        "table_statistics",
        "Table statistics (pg_stat_user_tables)",
        13,
        "pg_stat_user_tables",
        "Sequential/index access, tuple churn, vacuum/analyze and dead-tuple signals.",
        "pg_stat_user_tables",
        ("relid", "seq_scan", "idx_scan", "n_live_tup", "n_dead_tup"),
    ),
    CapabilitySpec(
        "index_statistics",
        "Index statistics (pg_stat_user_indexes)",
        13,
        "pg_stat_user_indexes",
        "Index usage and scan counters.",
        "pg_stat_user_indexes",
        ("indexrelid", "idx_scan", "idx_tup_read", "idx_tup_fetch"),
    ),
    CapabilitySpec(
        "statement_statistics",
        "Statement workload statistics (pg_stat_statements)",
        13,
        "pg_stat_statements",
        "Per-query execution, blocks, temp I/O and WAL counters.",
        "pg_stat_statements",
        ("dbid", "userid", "queryid", "calls", "total_exec_time", "shared_blks_read", "temp_blks_written"),
        requires_pgss=True,
    ),
    CapabilitySpec(
        "database_session_statistics",
        "Database session lifecycle statistics",
        14,
        "pg_stat_database",
        "Session time, active time, idle-in-transaction time and session termination counters.",
        "pg_stat_database",
        ("session_time", "active_time", "idle_in_transaction_time", "sessions", "sessions_abandoned", "sessions_fatal", "sessions_killed"),
    ),
    CapabilitySpec(
        "wal_statistics",
        "Cluster WAL statistics (pg_stat_wal)",
        14,
        "pg_stat_wal",
        "Cluster-level WAL volume, writes, syncs and WAL-buffer pressure.",
        "pg_stat_wal",
        ("wal_records", "wal_fpi", "wal_bytes", "wal_buffers_full"),
    ),
    CapabilitySpec(
        "shared_memory_statistics",
        "Cumulative statistics stored in shared memory",
        15,
        "statistics subsystem",
        "Removes the separate statistics collector process and improves monitoring access characteristics.",
        category="architecture",
    ),
    CapabilitySpec(
        "io_statistics",
        "Granular I/O statistics (pg_stat_io)",
        16,
        "pg_stat_io",
        "Breaks I/O down by backend type, context and object for better bottleneck diagnosis.",
        "pg_stat_io",
        ("backend_type", "object", "context", "reads", "writes"),
    ),
    CapabilitySpec(
        "last_table_scan",
        "Last sequential/index scan timestamps on tables",
        16,
        "pg_stat_user_tables",
        "Adds recency to scan counters and makes unused/rarely-used object analysis safer.",
        "pg_stat_user_tables",
        ("last_seq_scan", "last_idx_scan"),
    ),
    CapabilitySpec(
        "last_index_scan",
        "Last index scan timestamp",
        16,
        "pg_stat_user_indexes",
        "Shows when an index was last used, improving index-advisor confidence.",
        "pg_stat_user_indexes",
        ("last_idx_scan",),
    ),
    CapabilitySpec(
        "statement_local_io_timing",
        "Local-block I/O timing per statement",
        17,
        "pg_stat_statements",
        "Separates local-block read/write timing from shared-block timing.",
        "pg_stat_statements",
        ("local_blk_read_time", "local_blk_write_time"),
        requires_pgss=True,
    ),
    CapabilitySpec(
        "statement_stats_age",
        "Per-statement statistics age",
        17,
        "pg_stat_statements",
        "stats_since/minmax_stats_since make baselines and reset detection more reliable.",
        "pg_stat_statements",
        ("stats_since", "minmax_stats_since"),
        requires_pgss=True,
    ),
    CapabilitySpec(
        "database_parallel_workers",
        "Database parallel-worker demand/activity",
        18,
        "pg_stat_database",
        "Tracks requested versus actually launched parallel workers at database level.",
        "pg_stat_database",
        ("parallel_workers_to_launch", "parallel_workers_launched"),
    ),
    CapabilitySpec(
        "statement_parallel_workers",
        "Parallel-worker activity per statement",
        18,
        "pg_stat_statements",
        "Shows requested versus launched workers for individual query fingerprints.",
        "pg_stat_statements",
        ("parallel_workers_to_launch", "parallel_workers_launched"),
        requires_pgss=True,
    ),
    CapabilitySpec(
        "statement_wal_buffers_full",
        "WAL-buffer pressure per statement",
        18,
        "pg_stat_statements",
        "Associates full WAL buffers with specific statement fingerprints.",
        "pg_stat_statements",
        ("wal_buffers_full",),
        requires_pgss=True,
    ),
)


def major_from_version_num(version_num: int) -> int:
    return int(version_num) // 10000


def _relation_columns(conn, relation: str) -> set[str]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_attribute a
            WHERE a.attrelid = to_regclass(%s)
              AND a.attnum > 0
              AND NOT a.attisdropped
            """,
            (relation,),
        )
        return {row["attname"] for row in cur.fetchall()}


def _relation_exists(conn, relation: str) -> bool:
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass(%s) IS NOT NULL AS ok", (relation,))
        return bool(cur.fetchone()["ok"])


def _setting(conn, name: str) -> str | None:
    with conn.cursor() as cur:
        cur.execute("SELECT current_setting(%s, true) AS value", (name,))
        return cur.fetchone()["value"]


def lifecycle_info(major: int, *, today: date | None = None) -> dict[str, Any]:
    today = today or date.today()
    final = LIFECYCLE.get(major)
    if final is None:
        return {"known": False, "status": "unknown", "final_release": None, "days_remaining": None}
    days = (final - today).days
    if days < 0:
        status = "eol"
    elif days <= 120:
        status = "near_eol"
    else:
        status = "supported"
    return {"known": True, "status": status, "final_release": final.isoformat(), "days_remaining": days}


def support_info(major: int, expected_major: int | None = None) -> dict[str, Any]:
    if major < MIN_SUPPORTED_MAJOR:
        level = "unsupported"
    elif major > MAX_VALIDATED_MAJOR:
        level = "unvalidated_newer"
    else:
        level = "supported"
    return {
        "level": level,
        "supported_range": f"{MIN_SUPPORTED_MAJOR}-{MAX_VALIDATED_MAJOR}",
        "baseline_major": BASELINE_MAJOR,
        "expected_major": expected_major,
        "expected_major_match": expected_major is None or expected_major == major,
    }


def validate_major(major: int, expected_major: int | None = None) -> None:
    info = support_info(major, expected_major)
    if info["level"] == "unsupported":
        raise RuntimeError(
            f"PostgreSQL {major} is below the supported PG Intelligence range "
            f"{MIN_SUPPORTED_MAJOR}-{MAX_VALIDATED_MAJOR}"
        )
    if expected_major is not None and major != expected_major:
        raise RuntimeError(f"Source PostgreSQL major is {major}, but expected_major={expected_major}")


def _upgrade_benefits(major: int) -> list[dict[str, Any]]:
    benefits: list[dict[str, Any]] = []
    if major < 14:
        benefits.append({
            "from_major": 14,
            "title": "Richer database/session and WAL monitoring",
            "details": "pg_stat_database session lifecycle metrics, pg_stat_wal, and core query-id support improve incident correlation.",
        })
    if major < 15:
        benefits.append({
            "from_major": 15,
            "title": "Cumulative statistics in shared memory",
            "details": "PostgreSQL 15 removed the separate statistics collector process and stores cumulative statistics in shared memory.",
        })
    if major < 16:
        benefits.append({
            "from_major": 16,
            "title": "Granular I/O and scan-recency visibility",
            "details": "pg_stat_io plus last_seq_scan/last_idx_scan provide substantially better I/O and index-usage evidence.",
        })
    if major < 17:
        benefits.append({
            "from_major": 17,
            "title": "Richer pg_stat_statements timing and baseline metadata",
            "details": "Local-block I/O timing and stats_since/minmax_stats_since improve per-query diagnosis and reset-aware baselines.",
        })
    if major < 18:
        benefits.append({
            "from_major": 18,
            "title": "Parallel-worker and WAL-buffer visibility",
            "details": "Database/statement parallel-worker metrics and statement wal_buffers_full expose resource pressure that older releases cannot report directly.",
        })
        benefits.append({
            "from_major": 18,
            "title": "PostgreSQL 18 engine improvements",
            "details": "Asynchronous I/O, B-tree skip scan, hash/join improvements, and pg_upgrade retaining optimizer statistics can reduce operational and upgrade costs depending on workload.",
        })
    return benefits


def assess_source(conn, *, expected_major: int | None = None) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT current_setting('server_version') AS server_version,
                   current_setting('server_version_num')::int AS server_version_num
            """
        )
        version = cur.fetchone()

    major = major_from_version_num(version["server_version_num"])
    support = support_info(major, expected_major)
    lifecycle = lifecycle_info(major)

    pgss_installed = False
    with conn.cursor() as cur:
        cur.execute("SELECT EXISTS (SELECT 1 FROM pg_extension WHERE extname='pg_stat_statements') AS ok")
        pgss_installed = bool(cur.fetchone()["ok"])

    relation_cache: dict[str, tuple[bool, set[str]]] = {}

    def relation_info(name: str) -> tuple[bool, set[str]]:
        if name not in relation_cache:
            exists = _relation_exists(conn, name)
            relation_cache[name] = (exists, _relation_columns(conn, name) if exists else set())
        return relation_cache[name]

    caps: list[dict[str, Any]] = []
    for spec in CAPABILITIES:
        status = "available"
        missing_columns: list[str] = []
        if major < spec.min_major:
            status = "unavailable_version"
        elif spec.requires_pgss and not pgss_installed:
            status = "not_configured"
        elif spec.required_relation:
            exists, cols = relation_info(spec.required_relation)
            if not exists:
                status = "not_present"
            else:
                missing_columns = sorted(set(spec.required_columns) - cols)
                if missing_columns:
                    status = "not_present"
        caps.append({
            "key": spec.key,
            "label": spec.label,
            "category": spec.category,
            "source": spec.source,
            "min_major": spec.min_major,
            "status": status,
            "available": status == "available",
            "missing_columns": missing_columns,
            "benefit": spec.benefit,
        })

    settings = {
        "track_io_timing": _setting(conn, "track_io_timing"),
        "track_wal_io_timing": _setting(conn, "track_wal_io_timing"),
        "compute_query_id": _setting(conn, "compute_query_id"),
        "shared_preload_libraries": _setting(conn, "shared_preload_libraries"),
        "pg_stat_statements.track_planning": _setting(conn, "pg_stat_statements.track_planning") if pgss_installed else None,
    }

    config_notes: list[str] = []
    if settings["track_io_timing"] not in {"on", "true", "1"}:
        config_notes.append("track_io_timing is not enabled; PostgreSQL I/O timing counters may remain zero.")
    if major >= 14 and settings["track_wal_io_timing"] not in {"on", "true", "1"}:
        config_notes.append("track_wal_io_timing is not enabled; WAL write/sync timing counters may remain zero.")
    if not pgss_installed:
        config_notes.append("pg_stat_statements is not installed in this database; per-query workload monitoring is unavailable.")

    missing_vs_18 = [
        {"key": c["key"], "label": c["label"], "min_major": c["min_major"], "status": c["status"]}
        for c in caps
        if c["category"] == "monitoring" and not c["available"] and c["min_major"] <= BASELINE_MAJOR
    ]

    return {
        "server_version": version["server_version"],
        "server_version_num": version["server_version_num"],
        "server_major": major,
        "support": support,
        "lifecycle": lifecycle,
        "pg_stat_statements_installed": pgss_installed,
        "settings": settings,
        "configuration_notes": config_notes,
        "capabilities": caps,
        "missing_vs_pg18": missing_vs_18,
        "upgrade_to_pg18": _upgrade_benefits(major),
    }


def render_text(report: dict[str, Any]) -> str:
    support = report["support"]
    lifecycle = report["lifecycle"]
    lines = [
        "PG Intelligence - PostgreSQL compatibility assessment",
        f"Server           : PostgreSQL {report['server_version']}",
        f"Detected major   : {report['server_major']}",
        f"PG Intel support : {support['level']} (validated range {support['supported_range']})",
    ]
    if support.get("expected_major") is not None:
        lines.append(
            f"Expected major   : {support['expected_major']} "
            f"({'OK' if support['expected_major_match'] else 'MISMATCH'})"
        )
    if lifecycle["known"]:
        if lifecycle["status"] == "eol":
            lifecycle_text = f"EOL since {lifecycle['final_release']}"
        elif lifecycle["status"] == "near_eol":
            lifecycle_text = f"supported, near EOL ({lifecycle['final_release']}; {lifecycle['days_remaining']} days)"
        else:
            lifecycle_text = f"supported through {lifecycle['final_release']} ({lifecycle['days_remaining']} days)"
        lines.append(f"Community status : {lifecycle_text}")

    lines.extend(["", f"Monitoring capabilities (PostgreSQL {BASELINE_MAJOR} baseline)"])
    for cap in report["capabilities"]:
        mark = "OK" if cap["available"] else "--"
        suffix = ""
        if not cap["available"]:
            if cap["status"] == "unavailable_version":
                suffix = f" [requires PG{cap['min_major']}+]"
            elif cap["status"] == "not_configured":
                suffix = " [not configured]"
            elif cap["missing_columns"]:
                suffix = f" [missing: {', '.join(cap['missing_columns'])}]"
            else:
                suffix = f" [{cap['status']}]"
        lines.append(f"  [{mark}] {cap['label']}{suffix}")

    if report["configuration_notes"]:
        lines.extend(["", "Configuration notes"])
        lines.extend(f"  - {note}" for note in report["configuration_notes"])

    benefits = report["upgrade_to_pg18"]
    lines.extend(["", f"Upgrade perspective -> PostgreSQL {BASELINE_MAJOR}"])
    if benefits:
        for item in benefits:
            lines.append(f"  PG{item['from_major']}+: {item['title']}")
            lines.append(f"             {item['details']}")
    else:
        lines.append("  Already on the PostgreSQL 18 capability baseline.")

    if lifecycle.get("status") == "eol":
        lines.extend(["", "  IMPORTANT: this PostgreSQL major is end-of-life and no longer receives community security/bug fixes."])
    elif lifecycle.get("status") == "near_eol":
        lines.extend(["", "  NOTE: this PostgreSQL major is close to community end-of-life; migration planning is advisable."])

    return "\n".join(lines)
