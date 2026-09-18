import unittest
from datetime import datetime, timezone
from pgintel.repository import insert_query_samples

class FakeCursor:
    def __init__(self, conn): self.conn=conn; self._one=None; self.rowcount=0
    def __enter__(self): return self
    def __exit__(self,*a): return False
    def execute(self, sql, params=None):
        if sql.lstrip().startswith("SELECT * FROM pgintel.query_samples"):
            self._one=self.conn.prev
        elif "INSERT INTO pgintel.query_samples" in sql:
            self.conn.inserts.append(params); self.rowcount=1
        else:
            raise AssertionError(sql)
    def fetchone(self): return self._one
class FakeConn:
    def __init__(self, prev=None): self.prev=prev; self.inserts=[]
    def cursor(self): return FakeCursor(self)

def row(calls=10, plans=0):
    return {"dbid":1,"userid":2,"queryid":3,"toplevel":True,"query":None,"plans":plans,"calls":calls,
            "total_plan_time":0.0,"total_exec_time":100.0,"rows":10,"shared_blks_hit":10,"shared_blks_read":1,
            "temp_blks_read":0,"temp_blks_written":0,"wal_bytes":0}

class RepositorySafetyTests(unittest.TestCase):
    def test_first_statement_sample_is_kept_as_baseline(self):
        c=FakeConn(None); out=insert_query_samples(c,1,datetime.now(timezone.utc),[row()],store_query_text=False)
        self.assertEqual(len(out),1); self.assertEqual(len(c.inserts),1)
    def test_unchanged_statement_is_not_stored(self):
        prev={"plans_raw":0,"calls_raw":10,"total_plan_time_raw":0.0,"total_exec_time_raw":100.0,"rows_raw":10,
              "shared_blks_hit_raw":10,"shared_blks_read_raw":1,"temp_blks_read_raw":0,"temp_blks_written_raw":0,
              "wal_bytes_raw":0,"query_hash":None}
        c=FakeConn(prev); out=insert_query_samples(c,1,datetime.now(timezone.utc),[row()],store_query_text=False)
        self.assertEqual(out,[]); self.assertEqual(c.inserts,[])
    def test_changed_statement_is_stored(self):
        prev={"plans_raw":0,"calls_raw":9,"total_plan_time_raw":0.0,"total_exec_time_raw":90.0,"rows_raw":9,
              "shared_blks_hit_raw":9,"shared_blks_read_raw":1,"temp_blks_read_raw":0,"temp_blks_written_raw":0,
              "wal_bytes_raw":0,"query_hash":None}
        c=FakeConn(prev); out=insert_query_samples(c,1,datetime.now(timezone.utc),[row()],store_query_text=False)
        self.assertEqual(len(out),1); self.assertEqual(out[0]["calls_delta"],1)
if __name__=='__main__': unittest.main()
