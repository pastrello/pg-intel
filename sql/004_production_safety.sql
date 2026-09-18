-- PG Intelligence 0.1.4 - production-safety/collector-health migration
-- Apply to the PG Intelligence repository, not to the monitored application database.

CREATE TABLE IF NOT EXISTS pgintel.collection_cycles (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    cycle_duration_ms   double precision NOT NULL,
    source_duration_ms  double precision NOT NULL,
    repository_duration_ms double precision NOT NULL,
    slow_requested      boolean NOT NULL DEFAULT false,
    slow_collected      boolean NOT NULL DEFAULT false,
    sizes_requested     boolean NOT NULL DEFAULT false,
    sizes_collected     boolean NOT NULL DEFAULT false,
    budget_exceeded     boolean NOT NULL DEFAULT false,
    database_rows       integer NOT NULL DEFAULT 0,
    table_rows          integer NOT NULL DEFAULT 0,
    index_rows          integer NOT NULL DEFAULT 0,
    query_rows_seen     integer NOT NULL DEFAULT 0,
    query_rows_stored   integer NOT NULL DEFAULT 0,
    events_created      integer NOT NULL DEFAULT 0,
    collector_ms        jsonb NOT NULL DEFAULT '{}'::jsonb,
    notes               jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS collection_cycles_instance_time_idx
    ON pgintel.collection_cycles(instance_id, collected_at DESC);
