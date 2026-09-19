import unittest
from unittest.mock import patch

from pgintel.analyzer import Event, analyze_database, analyze_indexes, analyze_tables, persist_events
from pgintel.config import AgentConfig, DbConfig


CFG = AgentConfig(
    instance_name="test",
    source=DbConfig(""),
    repository=DbConfig(""),
    temp_bytes_alert=1000,
    large_unused_index_bytes=1000,
)


class _CooldownCursor:
    def __init__(self):
        self.rows = [{
            "event_type": "high_dead_tuple_ratio",
            "object_type": "table",
            "object_key": "public.t",
        }]
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params=None): pass
    def fetchall(self): return self.rows

class _CooldownConn:
    def cursor(self): return _CooldownCursor()


class AnalyzerTests(unittest.TestCase):
    def test_deadlock_and_temp_io(self):
        rows = [{
            "datname": "erp", "deadlocks_delta": 1, "temp_bytes_delta": 2000,
            "cache_hit_ratio": 0.99, "blks_hit_delta": 10000, "blks_read_delta": 10,
        }]
        events = analyze_database(rows, CFG)
        self.assertEqual({e.event_type for e in events}, {"deadlock", "high_temp_io"})

    def test_dead_tuples(self):
        rows = [{"schemaname": "public", "relname": "t", "n_live_tup": 8000, "n_dead_tup": 3000,
                 "dead_tuple_ratio": 3000/11000}]
        events = analyze_tables(rows, CFG)
        self.assertEqual(events[0].event_type, "high_dead_tuple_ratio")

    def test_unused_index_excludes_unique(self):
        base = {"schemaname": "public", "indexrelname": "idx", "index_size_bytes": 2000,
                "idx_scan": 0, "indisprimary": False, "indisunique": False}
        self.assertEqual(len(analyze_indexes([base], CFG)), 1)
        self.assertEqual(len(analyze_indexes([{**base, "indisunique": True}], CFG)), 0)

    def test_persistent_event_is_suppressed_but_deadlock_is_not(self):
        events = [
            Event("warning", "high_dead_tuple_ratio", "table", "public.t", "dead tuples", {}),
            Event("critical", "deadlock", "database", "erp", "deadlock", {}),
        ]
        with patch("pgintel.analyzer.insert_event") as insert:
            created, suppressed = persist_events(_CooldownConn(), 1, events, cooldown_seconds=3600)
        self.assertEqual(created, 1)
        self.assertEqual(suppressed, 1)
        self.assertEqual(insert.call_count, 1)
        self.assertEqual(insert.call_args.args[2], "critical")


if __name__ == "__main__":
    unittest.main()
