# Changelog

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
