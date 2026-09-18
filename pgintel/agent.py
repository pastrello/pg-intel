from __future__ import annotations

import logging
import time
from datetime import datetime, timezone

from .analyzer import (
    analyze_database,
    analyze_indexes,
    analyze_query_regressions,
    analyze_tables,
    persist_events,
)
from .collectors import database, indexes, server, statements, tables
from .config import AgentConfig
from .db import connect
from .repository import (
    ensure_instance,
    insert_database_samples,
    insert_index_samples,
    insert_query_samples,
    insert_server_sample,
    insert_table_samples,
)

LOG = logging.getLogger("pgintel")


def check(cfg: AgentConfig) -> dict:
    result = {"source": False, "repository": False, "pg_stat_statements": False, "pg_stat_statements_compatible": None}
    with connect(cfg.source.dsn) as src:
        s = server.collect(src)
        result["source"] = True
        result["server_version"] = s["server_version"]
        result["pg_stat_statements"] = statements.extension_available(src)
        if result["pg_stat_statements"]:
            compat = statements.compatibility_info(src)
            result["pg_stat_statements_compatible"] = compat["compatible"]
            result["pg_stat_statements_layout"] = compat["io_timing_layout"]
            result["pg_stat_statements_missing_columns"] = compat["missing_required_columns"]
    with connect(cfg.repository.dsn) as repo:
        with repo.cursor() as cur:
            cur.execute("SELECT to_regclass('pgintel.instances') AS repo_table")
            result["repository"] = cur.fetchone()["repo_table"] is not None
    return result


def collect_once(cfg: AgentConfig) -> dict:
    collected_at = datetime.now(timezone.utc)
    with connect(cfg.source.dsn) as src, connect(cfg.repository.dsn) as repo:
        server_row = server.collect(src)
        instance_id = ensure_instance(repo, cfg.instance_name, server_row)
        insert_server_sample(repo, instance_id, server_row)

        db_rows = database.collect(src)
        table_rows = tables.collect(src)
        index_rows = indexes.collect(src)
        query_rows = statements.collect(src) if statements.extension_available(src) else []

        derived_db = insert_database_samples(repo, instance_id, collected_at, db_rows)
        derived_tables = insert_table_samples(repo, instance_id, collected_at, table_rows)
        derived_indexes = insert_index_samples(repo, instance_id, collected_at, index_rows)
        derived_queries = insert_query_samples(
            repo, instance_id, collected_at, query_rows, store_query_text=cfg.store_query_text
        )

        events = []
        events.extend(analyze_database(derived_db, cfg))
        events.extend(analyze_tables(derived_tables, cfg))
        events.extend(analyze_indexes(derived_indexes, cfg))
        events.extend(analyze_query_regressions(repo, instance_id, derived_queries, cfg))
        persist_events(repo, instance_id, events)
        repo.commit()

        return {
            "instance_id": instance_id,
            "databases": len(db_rows),
            "tables": len(table_rows),
            "indexes": len(index_rows),
            "queries": len(query_rows),
            "events": len(events),
            "pg_stat_statements": bool(query_rows) or statements.extension_available(src),
        }


def run_forever(cfg: AgentConfig) -> None:
    LOG.info("Starting PG Intelligence agent for %s; interval=%ss", cfg.instance_name, cfg.interval_seconds)
    while True:
        started = time.monotonic()
        try:
            result = collect_once(cfg)
            LOG.info(
                "Collected: db=%d tables=%d indexes=%d queries=%d events=%d",
                result["databases"], result["tables"], result["indexes"], result["queries"], result["events"],
            )
        except KeyboardInterrupt:
            raise
        except Exception:
            LOG.exception("Collection cycle failed")
        elapsed = time.monotonic() - started
        time.sleep(max(1.0, cfg.interval_seconds - elapsed))
