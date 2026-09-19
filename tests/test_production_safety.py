import tempfile
import unittest
from pathlib import Path
from pgintel.config import load_config
from pgintel.collectors.database import _build_select as db_sql, _REQUIRED_COLUMNS as DB_BASE
from pgintel.collectors.tables import _build_select as table_sql
from pgintel.collectors.indexes import _build_select as index_sql
from pgintel.collectors.statements import _build_select as stmt_sql

STMT_BASE={"dbid","userid","queryid","calls","total_exec_time","rows","shared_blks_hit","shared_blks_read","temp_blks_read","temp_blks_written"}

class ProductionSafetyTests(unittest.TestCase):
    def test_fast_database_collection_avoids_size_function(self):
        sql=db_sql(set(DB_BASE),include_size=False)
        self.assertIn("NULL::bigint AS database_size_bytes",sql)
        self.assertNotIn("pg_database_size(d.datid) AS database_size_bytes",sql)
    def test_size_database_collection_uses_size_function(self):
        sql=db_sql(set(DB_BASE),include_size=True)
        self.assertIn("pg_database_size(d.datid) AS database_size_bytes",sql)
    def test_database_collection_is_scoped_to_current_database(self):
        sql=db_sql(set(DB_BASE),include_size=False)
        self.assertIn("WHERE d.datname = current_database()",sql)
    def test_table_fast_avoids_size_function(self):
        self.assertNotIn("pg_total_relation_size(s.relid) AS total_size_bytes",table_sql(include_size=False))
    def test_index_fast_avoids_size_function(self):
        self.assertNotIn("pg_relation_size(i.indexrelid) AS index_size_bytes",index_sql(include_size=False))
    def test_statement_default_uses_showtext_false(self):
        sql=stmt_sql(STMT_BASE,include_query_text=False)
        self.assertIn("FROM pg_stat_statements(false) AS s",sql)
        self.assertIn("NULL::text AS query",sql)
    def test_statement_all_text_uses_showtext_true(self):
        sql=stmt_sql(STMT_BASE|{"query"},include_query_text=True)
        self.assertIn("FROM pg_stat_statements(true) AS s",sql)
        self.assertIn("s.query AS query",sql)
    def test_statement_collection_is_scoped_to_current_database(self):
        sql=stmt_sql(STMT_BASE,include_query_text=False)
        self.assertIn("s.dbid = (",sql)
        self.assertIn("datname = current_database()",sql)
    def test_config_defaults_are_production_conservative(self):
        data='''[agent]\ninstance_name=x\n[source]\ndsn=x\n[repository]\ndsn=y\n'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.ini'; p.write_text(data)
            cfg=load_config(p)
        self.assertEqual(cfg.interval_seconds,60)
        self.assertEqual(cfg.slow_interval_seconds,900)
        self.assertEqual(cfg.size_interval_seconds,3600)
        self.assertEqual(cfg.query_text_mode,'none')
        self.assertEqual(cfg.event_cooldown_seconds,3600)
    def test_legacy_store_query_text_true_maps_to_all(self):
        data='''[agent]\ninstance_name=x\nstore_query_text=true\n[source]\ndsn=x\n[repository]\ndsn=y\n'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.ini'; p.write_text(data)
            cfg=load_config(p)
        self.assertEqual(cfg.query_text_mode,'all')
    def test_invalid_intervals_fail(self):
        data='''[agent]\ninstance_name=x\ninterval_seconds=60\n[collection]\nslow_interval_seconds=30\n[source]\ndsn=x\n[repository]\ndsn=y\n'''
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'c.ini'; p.write_text(data)
            with self.assertRaises(ValueError): load_config(p)
if __name__=='__main__': unittest.main()
