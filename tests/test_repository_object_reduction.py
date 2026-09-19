import unittest
from datetime import datetime, timezone

from pgintel.repository import insert_index_samples, insert_table_samples


class FakeCursor:
    def __init__(self, conn):
        self.conn = conn
        self._all = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def execute(self, sql, params=None):
        if sql.lstrip().startswith("SELECT DISTINCT ON"):
            self._all = list(self.conn.previous)
        else:
            raise AssertionError(sql)

    def executemany(self, sql, params_seq):
        rows = list(params_seq)
        self.conn.inserts.extend(rows)
        self.rowcount = len(rows)

    def fetchall(self):
        return self._all


class FakeConn:
    def __init__(self, previous):
        self.previous = previous
        self.inserts = []

    def cursor(self):
        return FakeCursor(self)


def table_row(**overrides):
    row = {
        "relid": 10,
        "schemaname": "public",
        "relname": "t",
        "seq_scan": 1,
        "seq_tup_read": 10,
        "idx_scan": 2,
        "idx_tup_fetch": 5,
        "n_tup_ins": 3,
        "n_tup_upd": 4,
        "n_tup_del": 1,
        "n_tup_hot_upd": 0,
        "n_live_tup": 100,
        "n_dead_tup": 5,
        "n_mod_since_analyze": 7,
        "last_vacuum": None,
        "last_autovacuum": None,
        "last_analyze": None,
        "last_autoanalyze": None,
        "vacuum_count": 0,
        "autovacuum_count": 0,
        "analyze_count": 0,
        "autoanalyze_count": 0,
        "total_size_bytes": None,
    }
    row.update(overrides)
    return row


def table_prev():
    return {
        "relid": 10,
        "seq_scan_raw": 1,
        "idx_scan_raw": 2,
        "n_tup_ins_raw": 3,
        "n_tup_upd_raw": 4,
        "n_tup_del_raw": 1,
        "n_live_tup": 100,
        "n_dead_tup": 5,
        "n_mod_since_analyze": 7,
        "last_vacuum": None,
        "last_autovacuum": None,
        "last_analyze": None,
        "last_autoanalyze": None,
        "total_size_bytes": None,
    }


def index_row(**overrides):
    row = {
        "relid": 10,
        "indexrelid": 20,
        "schemaname": "public",
        "relname": "t",
        "indexrelname": "t_idx",
        "idx_scan": 3,
        "idx_tup_read": 12,
        "idx_tup_fetch": 11,
        "index_size_bytes": None,
        "indisunique": False,
        "indisprimary": False,
        "indisvalid": True,
    }
    row.update(overrides)
    return row


def index_prev():
    return {
        "indexrelid": 20,
        "idx_scan_raw": 3,
        "idx_tup_read_raw": 12,
        "idx_tup_fetch_raw": 11,
        "index_size_bytes": None,
        "indisunique": False,
        "indisprimary": False,
        "indisvalid": True,
    }


class ObjectReductionTests(unittest.TestCase):
    def test_unchanged_table_is_not_stored(self):
        conn = FakeConn([table_prev()])
        out = insert_table_samples(conn, 1, datetime.now(timezone.utc), [table_row()])
        self.assertEqual(out, [])
        self.assertEqual(conn.inserts, [])

    def test_changed_table_is_stored(self):
        conn = FakeConn([table_prev()])
        out = insert_table_samples(conn, 1, datetime.now(timezone.utc), [table_row(n_dead_tup=6)])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(conn.inserts), 1)

    def test_unchanged_index_is_not_stored(self):
        conn = FakeConn([index_prev()])
        out = insert_index_samples(conn, 1, datetime.now(timezone.utc), [index_row()])
        self.assertEqual(out, [])
        self.assertEqual(conn.inserts, [])

    def test_changed_index_is_stored(self):
        conn = FakeConn([index_prev()])
        out = insert_index_samples(conn, 1, datetime.now(timezone.utc), [index_row(idx_scan=4)])
        self.assertEqual(len(out), 1)
        self.assertEqual(len(conn.inserts), 1)
        self.assertEqual(out[0]["idx_scan_delta"], 1)


if __name__ == "__main__":
    unittest.main()
