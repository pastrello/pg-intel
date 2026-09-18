# PG Intelligence 0.1.4 — production-safety profile

Version 0.1.4 is designed to reduce the observer effect when PG Intelligence is attached to a busy PostgreSQL 13–18 source.

## Collection classes

| Class | Default cadence | Purpose |
|---|---:|---|
| FAST | 60 s | server/session counters, `pg_stat_database`, `pg_stat_statements` counters |
| SLOW | 15 min | table/index statistics, dead tuples, vacuum/analyze and scan counters |
| SIZE | 60 min | `pg_database_size`, `pg_total_relation_size`, `pg_relation_size` |

The daemon starts with FAST-only cycles. SLOW and SIZE work become due after their configured interval. This avoids a large catalog/filesystem inventory immediately after every service restart.

Configuration:

```ini
[agent]
interval_seconds = 60

[collection]
slow_interval_seconds = 900
size_interval_seconds = 3600
max_source_cycle_seconds = 20
query_text_mode = none
```

`slow_interval_seconds` must be at least the FAST interval and `size_interval_seconds` must be at least the SLOW interval.

## Source-side time budget

`max_source_cycle_seconds` is a soft budget for source collector SQL. FAST collectors always run. If they consume the budget, SLOW/SIZE collectors are skipped for that scheduled interval rather than being repeatedly retried every minute.

The PostgreSQL monitoring role still has the independent server-side `statement_timeout` configured by `002_monitoring_role.sql`, so one slow SQL statement is also bounded at the database level.

## Query text policy

`pg_stat_statements(showtext => false)` is the default path. PostgreSQL documents this function specifically for external monitoring tools that want to avoid repeatedly fetching query texts stored in an external file.

Modes:

```ini
query_text_mode = none
```

Never retrieves SQL text. This is the default and lowest-impact/privacy-preserving mode.

```ini
query_text_mode = events
```

FAST collection still uses `showtext=false`. Query text is fetched only for query fingerprints that generate a query-regression event, and only while the source-cycle budget remains available.

```ini
query_text_mode = all
```

Retrieves SQL text for every `pg_stat_statements` entry. This retains the old `store_query_text=true` behavior and is not recommended for a high-intensity production source unless specifically required.

## Repository growth control

PG Intelligence still reads the current statement counters, but after the first baseline it does not insert a `query_samples` row when both `calls` and `plans` are unchanged. This avoids storing repeated copies of inactive historical entries.

`health` reports both rows seen and rows actually stored, including the reduction percentage.

## Relation sizes

Physical size functions are intentionally removed from FAST/SLOW cycles:

- `pg_database_size()` — SIZE cycle only
- `pg_total_relation_size()` — SIZE cycle only
- `pg_relation_size()` — SIZE cycle only

When a non-SIZE sample is persisted, the last known size is carried forward in the repository. The source does not need to recalculate it every minute.

## Collector health / observer-effect telemetry

0.1.4 persists one row per cycle in `pgintel.collection_cycles`, including:

- total cycle duration;
- source collector SQL duration;
- repository write duration;
- duration per collector as JSON;
- rows seen/stored;
- FAST/SLOW/SIZE decisions;
- source-budget overruns;
- event count.

View the last 24 hours:

```bash
pgintel -c /etc/pgintel/pgintel.ini health --hours 24
```

A useful production acceptance criterion is not a universal percentage. Instead, collect at least one representative business day and compare the PG Intelligence source duration, PostgreSQL CPU/I/O/latency, and application SLOs before deciding whether to shorten any interval.

## Repository migration from 0.1.3

Fresh 0.1.4 repositories created with `001_repository.sql` already include `collection_cycles`.

For an existing repository:

```bash
pgintel -c /etc/pgintel/pgintel.ini migrate-repository
```

Equivalent SQL is available in:

```text
sql/004_production_safety.sql
```

The migration modifies only the PG Intelligence telemetry repository. It never alters the monitored application database.

## Recommended first deployment on a busy production source

Start with the defaults above and `query_text_mode=none`. Validate manually:

```bash
pgintel -c /etc/pgintel/pgintel.ini check
pgintel -c /etc/pgintel/pgintel.ini collect
pgintel -c /etc/pgintel/pgintel.ini collect --full
```

Then enable the service and watch:

```bash
journalctl -u pgintel -f
pgintel -c /etc/pgintel/pgintel.ini health --hours 1
```

The full inventory is intentionally explicit (`collect --full`) because it includes relation-size calls.
