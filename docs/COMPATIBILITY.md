# PostgreSQL 13–18 compatibility

PG Intelligence 0.1.3 automatically reads `server_version_num` and adapts collectors to the capabilities exposed by the connected server. The supported/validated source range is PostgreSQL **13 through 18**.

An optional safety pin can be configured:

```ini
[source]
dsn = host=db.example port=5432 dbname=erp user=pgintel
expected_major = 13
```

If `expected_major` is omitted, detection is fully automatic. If it is supplied and the connected server has another major version, `check` and collection fail instead of silently monitoring the wrong target.

## Capability baseline

| Capability | PG13 | PG14 | PG15 | PG16 | PG17 | PG18 |
|---|:---:|:---:|:---:|:---:|:---:|:---:|
| Core `pg_stat_activity`, database/table/index statistics | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `pg_stat_statements` core workload metrics | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |
| `pg_stat_database` session lifecycle metrics | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| `pg_stat_wal` | — | ✓ | ✓ | ✓ | ✓ | ✓ |
| Cumulative statistics in shared memory | — | — | ✓ | ✓ | ✓ | ✓ |
| `pg_stat_io` | — | — | — | ✓ | ✓ | ✓ |
| Last table/index scan timestamps | — | — | — | ✓ | ✓ | ✓ |
| Local-block I/O timing in `pg_stat_statements` | — | — | — | — | ✓ | ✓ |
| `stats_since` / `minmax_stats_since` in `pg_stat_statements` | — | — | — | — | ✓ | ✓ |
| Database parallel-worker counters | — | — | — | — | — | ✓ |
| Statement parallel-worker counters | — | — | — | — | — | ✓ |
| Statement `wal_buffers_full` | — | — | — | — | — | ✓ |

PG Intelligence does not fabricate missing metrics. The compatibility layer either selects the real column when present or supplies a safe neutral value only where the current repository schema expects a field that did not exist in the older server. Core counters remain real PostgreSQL statistics.

## Version-specific notes

### PostgreSQL 13

Supported by PG Intelligence, including the legacy `pg_stat_statements.blk_read_time` / `blk_write_time` layout. PostgreSQL 13 does not expose the PG14 session lifecycle counters in `pg_stat_database`; PG Intelligence 0.1.3 detects this and uses neutral compatibility fields instead of failing the collector.

PostgreSQL 13 reached community end-of-life on 2025-11-13 and no longer receives community bug/security fixes.

### PostgreSQL 14

Adds session lifecycle statistics to `pg_stat_database`, cluster WAL statistics through `pg_stat_wal`, and core query-id computation used by `pg_stat_statements`. As of the 2026 lifecycle, community support ends on 2026-11-12.

### PostgreSQL 15

Moves cumulative statistics into shared memory and eliminates the separate statistics collector process. This changes how statistics are maintained internally, while the views consumed by PG Intelligence remain compatible.

### PostgreSQL 16

Adds `pg_stat_io` for granular I/O analysis and last-scan timestamps for tables/indexes. These are important future inputs for the PG Intelligence I/O and index advisors.

### PostgreSQL 17

`pg_stat_statements` renames shared I/O timing columns to `shared_blk_read_time` / `shared_blk_write_time` and adds local-block timing plus `stats_since` / `minmax_stats_since`. PG Intelligence discovers the installed view columns instead of assuming a fixed layout.

### PostgreSQL 18

Baseline used by the compatibility report. PostgreSQL 18 adds database/statement parallel-worker counters and `wal_buffers_full` per statement. It also introduces engine improvements such as asynchronous I/O, B-tree skip scan and `pg_upgrade` retaining optimizer statistics.

## Runtime assessment

```bash
pgintel -c /etc/pgintel/pgintel.ini capabilities
```

Machine-readable output:

```bash
pgintel -c /etc/pgintel/pgintel.ini capabilities --json
```

The report includes:

- detected version and major;
- PG Intelligence support range;
- PostgreSQL community lifecycle/EOL date;
- capability availability relative to PostgreSQL 18;
- missing configuration such as `pg_stat_statements` or I/O timing;
- upgrade benefits accumulated between the current major and PostgreSQL 18.

## Sources

- PostgreSQL versioning policy: https://www.postgresql.org/support/versioning/
- PostgreSQL 13 monitoring: https://www.postgresql.org/docs/13/monitoring-stats.html
- PostgreSQL 13 pg_stat_statements: https://www.postgresql.org/docs/13/pgstatstatements.html
- PostgreSQL 14 monitoring: https://www.postgresql.org/docs/14/monitoring-stats.html
- PostgreSQL 15 release notes: https://www.postgresql.org/docs/15/release-15.html
- PostgreSQL 16 release notes: https://www.postgresql.org/docs/16/release-16.html
- PostgreSQL 17 pg_stat_statements: https://www.postgresql.org/docs/17/pgstatstatements.html
- PostgreSQL 18 release notes: https://www.postgresql.org/docs/18/release-18.html
