import unittest

from pgintel.collectors.statements import _build_select


BASE = {
    "dbid", "userid", "queryid", "query", "calls", "total_exec_time", "rows",
    "shared_blks_hit", "shared_blks_read", "temp_blks_read", "temp_blks_written",
}


class StatementCollectorCompatibilityTests(unittest.TestCase):
    def test_postgresql_17_plus_io_timing_names_are_aliased(self):
        sql = _build_select(BASE | {"shared_blk_read_time", "shared_blk_write_time"})
        self.assertIn("s.shared_blk_read_time AS blk_read_time", sql)
        self.assertIn("s.shared_blk_write_time AS blk_write_time", sql)

    def test_legacy_io_timing_names_are_supported(self):
        sql = _build_select(BASE | {"blk_read_time", "blk_write_time"})
        self.assertIn("s.blk_read_time AS blk_read_time", sql)
        self.assertIn("s.blk_write_time AS blk_write_time", sql)

    def test_missing_optional_columns_get_safe_defaults(self):
        sql = _build_select(BASE)
        self.assertIn("0::bigint AS plans", sql)
        self.assertIn("0::numeric AS wal_bytes", sql)

    def test_missing_required_column_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, "queryid"):
            _build_select(BASE - {"queryid"})


if __name__ == "__main__":
    unittest.main()
