import unittest

from pgintel.bootstrap import (
    _connection_target,
    _preload_contains,
    _same_cluster,
    _same_database,
    _unsafe_role_attributes,
)


class BootstrapSafetyTests(unittest.TestCase):
    def test_connection_target(self):
        target = _connection_target("host=127.0.0.1 port=15333 dbname=erp user=pgintel")
        self.assertEqual(target["host"], "127.0.0.1")
        self.assertEqual(target["port"], "15333")
        self.assertEqual(target["dbname"], "erp")
        self.assertEqual(target["user"], "pgintel")

    def test_same_database_requires_same_endpoint_and_db(self):
        source = {"host": "127.0.0.1", "port": "15333", "dbname": "erp", "user": "pgintel"}
        repo = {"host": "127.0.0.1", "port": "15333", "dbname": "erp", "user": "pgintel_repo"}
        self.assertTrue(_same_cluster(source, repo))
        self.assertTrue(_same_database(source, repo))
        repo["dbname"] = "pgintel"
        self.assertFalse(_same_database(source, repo))

    def test_preload_parser(self):
        self.assertTrue(_preload_contains("pgaudit, pg_stat_statements", "pg_stat_statements"))
        self.assertFalse(_preload_contains("pgaudit", "pg_stat_statements"))

    def test_unsafe_role_attributes(self):
        row = {
            "rolsuper": False,
            "rolcreatedb": True,
            "rolcreaterole": False,
            "rolreplication": True,
            "rolbypassrls": False,
        }
        self.assertEqual(_unsafe_role_attributes(row), ["CREATEDB", "REPLICATION"])


if __name__ == "__main__":
    unittest.main()
