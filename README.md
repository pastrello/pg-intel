# PG Intelligence 0.1.4 — Prototype

A deliberately small PostgreSQL telemetry collector and deterministic analyzer. It is the data foundation for future query advisors, plan regression analysis, anomaly detection and AI/ML experiments.

## What this prototype does

- Connects to one monitored PostgreSQL database with a read-only monitoring role.
- Collects server, database, table, index and `pg_stat_statements` telemetry.
- Stores both raw cumulative counters and per-interval deltas in a PostgreSQL repository.
- Detects a few conservative conditions: deadlocks, heavy temporary I/O, high dead-tuple ratio, very large indexes with zero scans, and query-latency regression against a rolling median.
- Produces a simple CLI report.
- Does **not** modify the monitored database, run `EXPLAIN ANALYZE`, create indexes, execute recommendations, or call any LLM.

## Architecture

```text
Monitored PostgreSQL
       |
       | pg_monitor (read-only observation)
       v
 pgintel-agent  ---- deterministic analyzer
       |
       v
PG Intelligence repository
       |
       +---- history / events / future API & AI modules
```

## Requirements

- Python 3.9+
- Monitored PostgreSQL: **13 through 18** (automatic capability detection)
- PostgreSQL repository (design target: PostgreSQL 18; older repository versions are not the source-compatibility target)
- `psycopg` 3
- `pg_stat_statements` is optional but strongly recommended

## PostgreSQL 13–18 compatibility

PG Intelligence detects `server_version_num` automatically and adapts its SQL to the server capabilities. The current validated source range is PostgreSQL **13, 14, 15, 16, 17 and 18**.

```bash
pgintel -c /etc/pgintel/pgintel.ini capabilities
```

This command reports missing monitoring versus a PostgreSQL 18 baseline, lifecycle/EOL status, configuration gaps and the observability/engine benefits available by upgrading. See [`docs/COMPATIBILITY.md`](docs/COMPATIBILITY.md).

You can optionally pin the expected major as a safety check:

```ini
[source]
expected_major = 13
```

If omitted, detection is automatic.

## 1. Prepare the monitored PostgreSQL

In 0.1.5 the guided installer can create the dedicated monitoring role, grant `pg_monitor` and grant `CONNECT` to the configured source database. Existing safe roles are preserved; the bootstrap refuses to take over a pre-existing role with elevated attributes.

`pg_stat_statements` remains deliberately manual because enabling it may require a PostgreSQL restart. Typical setup requires it in `shared_preload_libraries`, an approved restart, then:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

The prototype assumes one application database per agent configuration. Multi-database discovery/collection is intentionally deferred.

## 2. Prepare the repository

The 0.1.5 bootstrap can create the dedicated `pgintel_repo` role, the `pgintel` database, initialize `sql/001_repository.sql` and apply repository migrations automatically. If the database already exists with another owner, bootstrap stops instead of altering it.

## 3. Install on RHEL-compatible Linux 8/9/10

Recommended guided installation:

```bash
sudo ./install-rocky.sh --configure
```

The installer creates the service account, virtualenv, protected configuration/`PGPASSFILE`, directories and systemd unit. At the end of `--configure`, it offers an idempotent bootstrap for PG Intelligence-specific roles/grants and the repository. It never changes `shared_preload_libraries`, never restarts PostgreSQL and never creates the `pg_stat_statements` extension automatically.

Installer targets are Rocky/RHEL/AlmaLinux-compatible 8, 9 and 10. CentOS 7 is legacy/best-effort; Ubuntu/Debian are not targets yet. See `docs/SEMI_PRODUCTION_HOWTO.md` for the complete procedure.

## 4. Validate

```bash
pgintel -c /etc/pgintel/pgintel.ini check
```

Expected shape:

```json
{
  "source": true,
  "repository": true,
  "pg_stat_statements": true,
  "server_version": "18.x ..."
}
```

## 5. First collections

The first collection establishes baselines, so most deltas are zero by design.

```bash
pgintel -c /etc/pgintel/pgintel.ini collect
sleep 60
pgintel -c /etc/pgintel/pgintel.ini collect
pgintel -c /etc/pgintel/pgintel.ini report --hours 24
```

Run continuously with:

```bash
pgintel -c /etc/pgintel/pgintel.ini run
```

A sample `pgintel.service` is included for systemd. Create a non-login OS user `pgintel` and adjust paths/permissions before enabling it.

## Security choices

- Monitoring role uses `pg_monitor`, not PostgreSQL superuser.
- Query text retrieval defaults to `none`; workload correlation uses PostgreSQL `queryid` plus database/user identity. A SHA-256 text hash is stored only when query text is explicitly retrieved (`events` or `all`).
- No SQL supplied by the monitoring target is executed by the repository.
- No automatic remediation exists in v0.1.
- The repository contains operational metadata and must itself be protected and backed up appropriately.

## Important prototype limitations

1. Table/index/query views are scoped to the source DSN's current database.
2. The implementation favors clarity over bulk-insert performance; later versions should batch inserts or use `COPY`.
3. Event deduplication/cooldown is not yet implemented, so a persistent condition can generate repeated events.
4. A zero-scan index means zero scans **since the PostgreSQL statistics reset**, not proof that the index is useless.
5. The cache-hit rule is deliberately coarse and is not an independent diagnosis of insufficient RAM.
6. Query regression compares interval latency with a rolling median and is a signal, not a root-cause conclusion.
7. Retention/partitioning is not yet implemented.

## Next logical milestones

- v0.2: batching, retention, partitioning, event cooldown and richer CLI health summary.
- v0.3: plan capture using safe `EXPLAIN (FORMAT JSON)` workflows and plan history.
- v0.4: REST API and small web portal.
- v0.5: AI explanation layer that consumes facts already derived by PG Intelligence rather than querying production freely.

The design principle is: **PostgreSQL provides the facts; higher-level intelligence explains them.**

## 0.1.1 compatibility fix

PostgreSQL 17 renamed the `pg_stat_statements` I/O timing columns
`blk_read_time`/`blk_write_time` to
`shared_blk_read_time`/`shared_blk_write_time`.

PG Intelligence 0.1.1 discovers the installed view columns at runtime and
normalizes both layouts to stable internal aliases. Optional statistics also
fall back to typed zero values when unavailable. The `check` command now
reports the detected `pg_stat_statements` layout and compatibility status.


## 0.1.2 installer / semi-production setup

The Rocky Linux installer is now idempotent and handles the service account,
virtualenv, permissions, systemd hardening, configuration skeleton and a
dedicated `PGPASSFILE`. For a guided install:

```bash
sudo ./install-rocky.sh --configure
```

The installer intentionally does not modify or restart the monitored PostgreSQL.
Apply `sql/002_monitoring_role.sql` once per monitored cluster and
`sql/003_monitored_database.sql` in each monitored database. Initialize the
repository with `sql/001_repository.sql`. The complete sequence is documented in
`docs/SEMI_PRODUCTION_HOWTO.md`.


## 0.1.4 production-safety profile

Version 0.1.4 changes the daemon from a single 60-second all-inventory loop to three collection classes:

```text
FAST  60 s   server + database counters + pg_stat_statements counters
SLOW  15 min table/index statistics
SIZE  60 min database/table/index physical sizes
```

The default statement path calls `pg_stat_statements(false)` and therefore does not retrieve SQL text. Configure `[collection] query_text_mode = events` to retrieve text only for a detected query-regression event, or `all` only when full query-text retention is explicitly required.

A soft source-side budget skips optional SLOW/SIZE work when FAST monitoring itself is taking too long. The new `health` command makes the observer effect measurable:

```bash
pgintel -c /etc/pgintel/pgintel.ini health --hours 24
```

`pgintel collect` is FAST-only by default. Use an explicit full inventory when desired:

```bash
pgintel -c /etc/pgintel/pgintel.ini collect --full
```

Existing 0.1.3 repositories require the idempotent telemetry-repository migration before the service is restarted:

```bash
pgintel -c /etc/pgintel/pgintel.ini migrate-repository
```

See `docs/PRODUCTION_SAFETY.md` for deployment guidance and the exact overhead controls.


## 0.1.5 guided PostgreSQL bootstrap

A fresh installation can now use one guided flow:

```bash
sudo ./install-rocky.sh --configure
```

After writing `pgintel.ini` and `pgpass`, accept the bootstrap prompt. The installer can create only the missing PG Intelligence objects:

```text
source cluster
  pgintel role
  + pg_monitor
  + CONNECT on monitored database

repository cluster
  pgintel_repo role
  pgintel database
  pgintel.* schema/tables
  repository migrations
```

Administrative passwords are used only for the bootstrap process and are not persisted in `pgintel.ini` or `pgpass`. Service passwords remain in the protected `PGPASSFILE`.

The bootstrap intentionally stops instead of making risky assumptions when:
- source and repository are configured as the same database;
- source and repository use the same role on the same cluster;
- an existing PG Intelligence role has elevated attributes;
- an existing repository database is owned by another role.

The remaining manual PostgreSQL step is `pg_stat_statements` preload/restart/extension creation.
