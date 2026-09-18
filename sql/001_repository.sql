CREATE SCHEMA IF NOT EXISTS pgintel;

CREATE TABLE IF NOT EXISTS pgintel.instances (
    id                  bigserial PRIMARY KEY,
    name                text NOT NULL UNIQUE,
    created_at          timestamptz NOT NULL DEFAULT now(),
    last_seen_at        timestamptz,
    server_version      text,
    server_version_num  integer,
    postmaster_start_time timestamptz
);

CREATE TABLE IF NOT EXISTS pgintel.server_samples (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    connections         integer NOT NULL,
    active_connections  integer NOT NULL,
    waiting_connections integer NOT NULL
);
CREATE INDEX IF NOT EXISTS server_samples_instance_time_idx
    ON pgintel.server_samples(instance_id, collected_at DESC);

CREATE TABLE IF NOT EXISTS pgintel.database_samples (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    datid               oid NOT NULL,
    datname             text NOT NULL,
    numbackends         integer,
    database_size_bytes bigint,
    stats_reset         timestamptz,
    xact_commit_raw     bigint,
    xact_rollback_raw   bigint,
    blks_read_raw       bigint,
    blks_hit_raw        bigint,
    temp_files_raw      bigint,
    temp_bytes_raw      bigint,
    deadlocks_raw       bigint,
    xact_commit_delta   bigint,
    xact_rollback_delta bigint,
    blks_read_delta     bigint,
    blks_hit_delta      bigint,
    temp_files_delta    bigint,
    temp_bytes_delta    bigint,
    deadlocks_delta     bigint,
    cache_hit_ratio     double precision
);
CREATE INDEX IF NOT EXISTS database_samples_instance_db_time_idx
    ON pgintel.database_samples(instance_id, datid, collected_at DESC);

CREATE TABLE IF NOT EXISTS pgintel.table_samples (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    relid               oid NOT NULL,
    schemaname          text NOT NULL,
    relname             text NOT NULL,
    total_size_bytes    bigint,
    seq_scan_raw        bigint,
    idx_scan_raw        bigint,
    n_tup_ins_raw       bigint,
    n_tup_upd_raw       bigint,
    n_tup_del_raw       bigint,
    seq_scan_delta      bigint,
    idx_scan_delta      bigint,
    n_tup_ins_delta     bigint,
    n_tup_upd_delta     bigint,
    n_tup_del_delta     bigint,
    n_live_tup          bigint,
    n_dead_tup          bigint,
    dead_tuple_ratio    double precision,
    n_mod_since_analyze bigint,
    last_vacuum         timestamptz,
    last_autovacuum     timestamptz,
    last_analyze        timestamptz,
    last_autoanalyze    timestamptz
);
CREATE INDEX IF NOT EXISTS table_samples_instance_rel_time_idx
    ON pgintel.table_samples(instance_id, relid, collected_at DESC);

CREATE TABLE IF NOT EXISTS pgintel.index_samples (
    id                  bigserial PRIMARY KEY,
    instance_id         bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at        timestamptz NOT NULL,
    indexrelid          oid NOT NULL,
    relid               oid NOT NULL,
    schemaname          text NOT NULL,
    relname             text NOT NULL,
    indexrelname        text NOT NULL,
    index_size_bytes    bigint,
    idx_scan_raw        bigint,
    idx_scan_delta      bigint,
    idx_tup_read_raw    bigint,
    idx_tup_fetch_raw   bigint,
    indisunique         boolean,
    indisprimary        boolean,
    indisvalid          boolean
);
CREATE INDEX IF NOT EXISTS index_samples_instance_index_time_idx
    ON pgintel.index_samples(instance_id, indexrelid, collected_at DESC);

CREATE TABLE IF NOT EXISTS pgintel.query_samples (
    id                       bigserial PRIMARY KEY,
    instance_id              bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    collected_at             timestamptz NOT NULL,
    dbid                     oid NOT NULL,
    userid                   oid NOT NULL,
    queryid                  bigint NOT NULL,
    toplevel                 boolean,
    query_hash               text,
    query_text               text,
    plans_raw                bigint,
    calls_raw                bigint,
    total_plan_time_raw      double precision,
    total_exec_time_raw      double precision,
    rows_raw                 bigint,
    shared_blks_hit_raw      bigint,
    shared_blks_read_raw     bigint,
    temp_blks_read_raw       bigint,
    temp_blks_written_raw    bigint,
    wal_bytes_raw            numeric,
    plans_delta              bigint,
    calls_delta              bigint,
    total_plan_time_delta    double precision,
    total_exec_time_delta    double precision,
    rows_delta               bigint,
    shared_blks_hit_delta    bigint,
    shared_blks_read_delta   bigint,
    temp_blks_read_delta     bigint,
    temp_blks_written_delta  bigint,
    wal_bytes_delta          numeric,
    mean_exec_time_ms        double precision
);
CREATE INDEX IF NOT EXISTS query_samples_instance_query_time_idx
    ON pgintel.query_samples(instance_id, dbid, userid, queryid, collected_at DESC);

CREATE TABLE IF NOT EXISTS pgintel.events (
    id              bigserial PRIMARY KEY,
    instance_id     bigint NOT NULL REFERENCES pgintel.instances(id) ON DELETE CASCADE,
    created_at      timestamptz NOT NULL DEFAULT now(),
    severity        text NOT NULL CHECK (severity IN ('info','warning','critical')),
    event_type      text NOT NULL,
    object_type     text,
    object_key      text,
    title           text NOT NULL,
    details         jsonb NOT NULL DEFAULT '{}'::jsonb
);
CREATE INDEX IF NOT EXISTS events_instance_time_idx
    ON pgintel.events(instance_id, created_at DESC);


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
