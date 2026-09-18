# Changelog

## 0.1.4 - 2026-09-18

- Add a production-safety collection scheduler: FAST 60s, SLOW 15min and SIZE 60min by default.
- Use `pg_stat_statements(false)` by default so query text is not repeatedly read from the source.
- Add `query_text_mode = none|events|all`; default is `none` and `events` retrieves text only for query-regression events.
- Move `pg_database_size`, `pg_total_relation_size` and `pg_relation_size` to SIZE cycles only.
- Carry the last known relation/database size forward in repository samples between SIZE cycles.
- Stop persisting unchanged `pg_stat_statements` rows after the first baseline, reducing repository growth.
- Add a soft source collector budget; optional SLOW/SIZE work is skipped when FAST collection consumes it.
- Add `pgintel health` and `pgintel.collection_cycles` to measure collector overhead and row reduction.
- Add idempotent `pgintel migrate-repository` and `sql/004_production_safety.sql` for upgrades.
- Make `pgintel collect` FAST-only by default; `collect --full` explicitly includes object and size inventory.
- Expand the unit-test suite to 33 tests.


## 0.1.3 - 2026-09-18

- Add validated source compatibility for PostgreSQL 13 through 18.
- Auto-detect the source major using `server_version_num`; optional `expected_major` provides a safety pin.
- Make `pg_stat_database` capability-aware so PostgreSQL 13 no longer fails on PG14+ session columns.
- Add `pgintel capabilities` / `--json` with a PostgreSQL 18 capability baseline.
- Report PostgreSQL community lifecycle/EOL status and upgrade benefits through PG18.
- Detect monitoring/configuration gaps including `pg_stat_wal`, `pg_stat_io`, last-scan timestamps, richer PG17 statement I/O, and PG18 parallel-worker/WAL-buffer metrics.
- Add installer `--assess` mode and best-effort capability assessment during interactive installation.
- Make the installer work from both release bundles and a source-only Git checkout without `dist/`.
- Expand unit tests from 12 to 21.

## 0.1.2 - 2026-09-17

- Rewrite the Rocky Linux installer for idempotent install/upgrade.
- Fix service-read access to `pgintel.ini` (`0640 root:pgintel`).
- Create `/var/lib/pgintel` and `/var/log/pgintel` with correct ownership.
- Add `/etc/pgintel/pgpass` (`0600 pgintel:pgintel`) and set `PGPASSFILE` in systemd.
- Add optional interactive `--configure` setup without embedding passwords in the INI.
- Add `--enable` validation gate before starting a new service.
- Preserve existing configuration on upgrades; validate before restarting an active service.
- Harden the source monitoring role as read-only with conservative timeouts.
- Add database-level `003_monitored_database.sql`.
- Add a semi-production installation HOW-TO.
- Add additional systemd sandboxing/hardening.

## 0.1.1 - 2026-09-15

- Fix PostgreSQL 17/18 `pg_stat_statements` compatibility after the I/O timing
  column rename from `blk_read_time`/`blk_write_time` to
  `shared_blk_read_time`/`shared_blk_write_time`.
- Discover `pg_stat_statements` columns at runtime and normalize supported
  layouts to stable internal aliases.
- Add compatibility details to `pgintel check`.
- Add safe defaults for optional `pg_stat_statements` metrics.
- Fix setuptools package discovery so the project builds cleanly with the
  top-level `sql/` directory present.
- Add compatibility unit tests (12 tests total).
