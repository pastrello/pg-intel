import unittest

from pgintel.analyzer import analyze_database, analyze_indexes, analyze_tables
from pgintel.config import AgentConfig, DbConfig


CFG = AgentConfig(
    instance_name="test",
    source=DbConfig(""),
    repository=DbConfig(""),
    temp_bytes_alert=1000,
    large_unused_index_bytes=1000,
)


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


if __name__ == "__main__":
    unittest.main()
