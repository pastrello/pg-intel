import unittest

from pgintel.collectors.database import _build_select, _REQUIRED_COLUMNS


class DatabaseCollectorCompatibilityTests(unittest.TestCase):
    def test_pg13_layout_uses_safe_defaults_for_newer_columns(self):
        sql = _build_select(set(_REQUIRED_COLUMNS))
        self.assertIn("0::double precision AS session_time", sql)
        self.assertIn("0::bigint AS sessions", sql)
        self.assertIn("0::bigint AS parallel_workers_to_launch", sql)

    def test_pg14_layout_uses_real_session_columns(self):
        cols = set(_REQUIRED_COLUMNS) | {
            "session_time", "active_time", "idle_in_transaction_time", "sessions",
            "sessions_abandoned", "sessions_fatal", "sessions_killed",
        }
        sql = _build_select(cols)
        self.assertIn("d.session_time AS session_time", sql)
        self.assertIn("d.sessions_killed AS sessions_killed", sql)
        self.assertIn("0::bigint AS parallel_workers_to_launch", sql)

    def test_pg18_layout_uses_parallel_worker_columns(self):
        cols = set(_REQUIRED_COLUMNS) | set({
            "session_time", "active_time", "idle_in_transaction_time", "sessions",
            "sessions_abandoned", "sessions_fatal", "sessions_killed",
            "parallel_workers_to_launch", "parallel_workers_launched",
        })
        sql = _build_select(cols)
        self.assertIn("d.parallel_workers_to_launch AS parallel_workers_to_launch", sql)
        self.assertIn("d.parallel_workers_launched AS parallel_workers_launched", sql)

    def test_missing_core_column_fails(self):
        with self.assertRaisesRegex(RuntimeError, "xact_commit"):
            _build_select(set(_REQUIRED_COLUMNS) - {"xact_commit"})


if __name__ == "__main__":
    unittest.main()
