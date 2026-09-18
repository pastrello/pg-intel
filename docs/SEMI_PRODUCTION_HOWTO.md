# PG Intelligence 0.1.3 — Semi-production HOW-TO

This procedure keeps the monitored PostgreSQL side read-only and separates it
from the telemetry repository.

## 1. Install the agent host

From the extracted project directory:

```bash
sudo ./install-rocky.sh --configure
```

The installer creates:

- `/opt/pg-intelligence` — application + virtualenv
- `/etc/pgintel/pgintel.ini` — DSNs without passwords (`0640 root:pgintel`)
- `/etc/pgintel/pgpass` — source/repository passwords (`0600 pgintel:pgintel`)
- `/var/lib/pgintel` — service state/home
- `/var/log/pgintel` — reserved application log directory
- `/etc/systemd/system/pgintel.service`

It does **not** modify or restart PostgreSQL and does **not** start a new agent by
default.

## 2. Prepare the monitored PostgreSQL cluster

### 2.1 Confirm `pg_stat_statements` preload

As a PostgreSQL administrator:

```sql
SHOW shared_preload_libraries;
```

If `pg_stat_statements` is not listed, add it to the PostgreSQL configuration,
for example:

```conf
shared_preload_libraries = 'pg_stat_statements'
```

If other libraries already exist, preserve them, for example:

```conf
shared_preload_libraries = 'pgaudit,pg_stat_statements'
```

A change to `shared_preload_libraries` requires a PostgreSQL restart. Plan this
for an approved maintenance window.

### 2.2 Create/harden the monitoring role (once per cluster)

From the agent package, run as a PostgreSQL administrator:

```bash
psql -h SOURCE_HOST -p 5432 -U postgres -d postgres \
  -f /opt/pg-intelligence/sql/002_monitoring_role.sql
```

Then set the role password according to your authentication policy. Example:

```bash
psql -h SOURCE_HOST -p 5432 -U postgres -d postgres
```

```sql
\password pgintel
```

The script grants `pg_monitor` and additionally forces the role to read-only,
with conservative statement/lock/idle transaction timeouts.

### 2.3 Enable the extension in the database being monitored

Run once in each monitored database:

```bash
psql -h SOURCE_HOST -p 5432 -U postgres -d erp \
  -f /opt/pg-intelligence/sql/003_monitored_database.sql
```

Verify:

```bash
psql -h SOURCE_HOST -p 5432 -U postgres -d erp -c \
  "SELECT extname, extversion FROM pg_extension WHERE extname='pg_stat_statements';"
```

Optional direct validation as the monitoring user:

```bash
PGPASSWORD='TEMPORARY_TEST_ONLY' psql -h SOURCE_HOST -p 5432 -U pgintel -d erp \
  -c "SELECT count(*) FROM pg_stat_statements;"
```

Avoid `PGPASSWORD` in routine operation; it is shown only as a one-off test.
The systemd service uses `/etc/pgintel/pgpass` instead.

## 3. Prepare the repository PostgreSQL

The repository may be on the agent host or on a separate PostgreSQL instance.
As an administrator of the repository server:

```sql
CREATE ROLE pgintel_repo LOGIN PASSWORD 'USE_A_REAL_PASSWORD';
CREATE DATABASE pgintel OWNER pgintel_repo;
```

Then initialize the schema while connected **as `pgintel_repo`** (or another
owner with equivalent rights):

```bash
psql -h REPOSITORY_HOST -p 5432 -U pgintel_repo -d pgintel \
  -f /opt/pg-intelligence/sql/001_repository.sql
```

Verify:

```bash
psql -h REPOSITORY_HOST -p 5432 -U pgintel_repo -d pgintel -c \
  "SELECT tablename FROM pg_tables WHERE schemaname='pgintel' ORDER BY tablename;"
```

## 4. Review agent connection configuration

```bash
sudo cat /etc/pgintel/pgintel.ini
sudo -u pgintel cat /etc/pgintel/pgpass
```

Expected source DSN shape:

```ini
[source]
dsn = host=SOURCE_HOST port=5432 dbname=erp user=pgintel connect_timeout=5 application_name=pgintel-agent
```

Expected repository DSN shape:

```ini
[repository]
dsn = host=REPOSITORY_HOST port=5432 dbname=pgintel user=pgintel_repo connect_timeout=5 application_name=pgintel-agent
```

`pgpass` format:

```text
SOURCE_HOST:5432:erp:pgintel:SOURCE_PASSWORD
REPOSITORY_HOST:5432:pgintel:pgintel_repo:REPOSITORY_PASSWORD
```

Permissions must be:

```bash
sudo chown pgintel:pgintel /etc/pgintel/pgpass
sudo chmod 600 /etc/pgintel/pgpass
sudo chown root:pgintel /etc/pgintel/pgintel.ini
sudo chmod 640 /etc/pgintel/pgintel.ini
```

## 5. Assess version and capabilities

After the monitoring role/authentication exists, run:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini capabilities
```

The source major is auto-detected. The report compares the server with the PostgreSQL 18 monitoring baseline, shows lifecycle/EOL status and explains which observability features become available after an upgrade.

If you want to guarantee that this agent is connected to a specific major, add for example:

```ini
[source]
expected_major = 13
```

A mismatch causes validation/collection to fail. Omit the setting for automatic detection.

See `docs/COMPATIBILITY.md` for the PG13–18 matrix.

## 6. Validate before starting the daemon

Run with exactly the same OS user and password file used by systemd:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel \
  -c /etc/pgintel/pgintel.ini check
```

The important fields should be true:

```text
source: true
repository: true
pg_stat_statements: true
pg_stat_statements_compatible: true
```

## 7. Perform two manual collections

First sample establishes the baseline:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel -c /etc/pgintel/pgintel.ini collect
```

Wait at least one collection interval (default: 60 s), then:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel -c /etc/pgintel/pgintel.ini collect
```

Generate a report:

```bash
sudo -u pgintel env PGPASSFILE=/etc/pgintel/pgpass \
  /opt/pg-intelligence/venv/bin/pgintel -c /etc/pgintel/pgintel.ini report --hours 24
```

## 8. Enable continuous collection

```bash
sudo systemctl enable --now pgintel
sudo systemctl status pgintel
sudo journalctl -u pgintel -f
```

Or let the installer validate before enabling:

```bash
sudo ./install-rocky.sh --enable
```

`--enable` refuses to start the new service if `pgintel check` fails.

## 9. Semi-production safety checks

Before leaving it running:

```sql
-- On monitored PostgreSQL
\du+ pgintel
SHOW shared_preload_libraries;
SELECT current_database(), count(*) FROM pg_stat_statements GROUP BY 1;
```

```bash
# On agent host
systemctl cat pgintel
ls -ld /etc/pgintel /var/lib/pgintel /var/log/pgintel
ls -l /etc/pgintel/pgintel.ini /etc/pgintel/pgpass
journalctl -u pgintel --since '30 minutes ago' --no-pager
```

The monitored-side role should not have superuser, createdb, createrole,
replication, bypassrls, or application-table write grants.

## Upgrade from 0.1.1 / 0.1.2

Copy/extract 0.1.3 (or `git pull` in a source checkout) and run:

```bash
sudo ./install-rocky.sh
```

Existing `/etc/pgintel/pgintel.ini` is preserved and corrected to
`root:pgintel 0640`; `/etc/pgintel/pgpass` is created if absent. If the service
was already active, the installer runs a validation and restarts it only when
the validation succeeds.

No repository schema migration is required when upgrading from 0.1.1/0.1.2 to 0.1.3.
