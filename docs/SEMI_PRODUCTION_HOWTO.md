# PG Intelligence 0.1.6 — Semi-production HOW-TO

This procedure keeps application objects untouched, gives the source agent only observation privileges, and stores telemetry in a separate PostgreSQL database.

## 1. Supported installer platforms

The 0.1.5 installer targets the RHEL family:

- Rocky Linux 8, 9 and 10
- RHEL 8, 9 and 10
- AlmaLinux 8, 9 and 10 by compatible packaging
- CentOS 7: legacy/best-effort only
- Ubuntu/Debian: not an installer target yet

On RHEL-family 8 the installer selects Python 3.9+ (preferring an already usable runtime), validates `ssl`, `pyexpat`, pip and venv, and can repair the Python 3.12/Expat partial-update condition through distro RPMs.

## 2. Guided installation

From the extracted project directory:

```bash
sudo ./install-rocky.sh --configure
```

The installer creates/maintains:

```text
/opt/pg-intelligence
/etc/pgintel/pgintel.ini
/etc/pgintel/pgpass
/var/lib/pgintel
/var/log/pgintel
/etc/systemd/system/pgintel.service
```

It asks for two ordinary service connections:

```text
SOURCE
  host / port / monitored database / monitoring role

REPOSITORY
  host / port / repository database / repository role
```

Passwords for those service roles are stored only in `/etc/pgintel/pgpass` with mode `0600`.

At the end of `--configure`, the installer asks:

```text
Bootstrap PG Intelligence roles/repository now? [Y/n]:
```

Accepting this prompt asks for PostgreSQL administrative credentials. Administrative passwords are used only by that bootstrap process and are not written to `pgintel.ini`, `pgpass`, or command-line arguments.

## 3. What bootstrap creates

The bootstrap is idempotent.

### Monitored/source PostgreSQL

If needed it creates the configured monitoring role (normally `pgintel`) as a non-privileged LOGIN role, with conservative read-only/time-out settings.

It ensures:

```text
GRANT pg_monitor
GRANT CONNECT on the configured monitored database
```

If the role already exists, its password and role attributes are not reset. The bootstrap validates that it is a LOGIN role and refuses to take over a pre-existing role with `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION` or `BYPASSRLS`.

### Repository PostgreSQL

If needed it creates:

```text
role:     pgintel_repo
database: pgintel
owner:    pgintel_repo
schema:   pgintel
tables:   instances, samples, events, collection_cycles, ...
```

It then applies all repository migrations known by the installed version.

If a database with the configured repository name already exists but belongs to a different owner, bootstrap stops instead of changing ownership.

### Separation guard

Source and repository must not be the same configured database.

For example, this is correct:

```ini
[source]
dsn = host=127.0.0.1 port=15333 dbname=erp user=pgintel ...

[repository]
dsn = host=127.0.0.1 port=15333 dbname=pgintel user=pgintel_repo ...
```

This is refused:

```text
source     -> 127.0.0.1:15333 / erp
repository -> 127.0.0.1:15333 / erp
```

The guard exists specifically to prevent telemetry schema creation inside the application database.

## 4. Manual pg_stat_statements step

This remains manual because `shared_preload_libraries` may require a PostgreSQL restart.

Check:

```sql
SHOW shared_preload_libraries;
```

If `pg_stat_statements` is missing, add it while preserving existing libraries:

```conf
shared_preload_libraries = 'pgaudit,pg_stat_statements'
```

Restart PostgreSQL only in an approved maintenance window.

Then, in the monitored database:

```sql
CREATE EXTENSION IF NOT EXISTS pg_stat_statements;
```

The installer reports whether preload and extension are already present, but it does not change either one.

## 5. Rerun bootstrap without rewriting configuration

After `pgintel.ini` already exists:

```bash
sudo ./install-rocky.sh --bootstrap-postgres
```

This is useful after an upgrade or when a repository object was not yet initialized.

The older explicit repository-only migration remains available:

```bash
sudo ./install-rocky.sh --migrate-repository
```

## 6. Validate

Run with the exact service identity:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini check
```

Then inspect capabilities:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini capabilities
```

## 7. First collection

FAST-only:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini collect
```

Optional one-off full inventory:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini collect --full
```

## 8. Enable continuous collection

```bash
sudo ./install-rocky.sh --enable
```

or:

```bash
sudo systemctl enable --now pgintel
sudo systemctl status pgintel
sudo journalctl -u pgintel -f
```

`--enable` refuses to start a new service when `pgintel check` fails.

## 9. Upgrade behavior

Normal code upgrade preserves `/etc/pgintel/pgintel.ini` and `/etc/pgintel/pgpass`.

For an existing installation:

```bash
sudo ./install-rocky.sh --bootstrap-postgres
sudo ./install-rocky.sh --enable
```

Bootstrap initializes a missing PG Intelligence repository and applies repository migrations when necessary. It does not modify application tables, PostgreSQL preload configuration, or PostgreSQL service state.

## 10. Manual SQL scripts

The SQL directory remains available for audit, troubleshooting or intentionally manual deployments:

```text
001_repository.sql
    repository schema

002_monitoring_role.sql
    manual equivalent of source monitoring-role setup

003_monitored_database.sql
    manual pg_stat_statements extension setup after preload/restart

004_production_safety.sql
    historical 0.1.4 repository migration
```

For 0.1.5 guided installs, these no longer need to be applied manually except the deliberate `pg_stat_statements` extension step.


## 11. Upgrade from 0.1.5 to 0.1.6

Install the 0.1.6 code first. Existing configuration and `pgpass` are preserved.

Apply the repository migration before restarting collection:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini migrate-repository
```

or rerun the idempotent PostgreSQL bootstrap:

```bash
sudo ./install-rocky.sh --bootstrap-postgres
```

Then validate:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini check
```

The output should include:

```text
source: true
repository: true
repository_schema_0_1_4: true
repository_schema_0_1_6: true
```

For a clean 0.1.6 baseline while preserving 0.1.5 test history, change only the logical instance name, for example:

```ini
[agent]
instance_name = rocky-replica-erp
```

The old `lab-pg18` instance and its samples remain available in the repository for before/after comparison.

After at least one FAST cycle and one SLOW/SIZE cycle:

```bash
pgintel -c /etc/pgintel/pgintel.ini health --hours 24
```

Compare source/repository latency and table/index/query seen-vs-stored ratios with the preserved 0.1.5 measurements.
