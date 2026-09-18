-- PG Intelligence - MANUAL database-level pg_stat_statements setup
-- Run in EACH monitored database only after shared_preload_libraries is correct
-- and PostgreSQL has been restarted if that setting changed.
-- The 0.1.5 installer bootstrap handles the monitoring role and CONNECT grant.
-- pg_stat_statements must already be present in shared_preload_libraries;
-- changing shared_preload_libraries requires a PostgreSQL restart.

CREATE EXTENSION IF NOT EXISTS pg_stat_statements;

-- Useful when CONNECT has been revoked from PUBLIC in hardened environments.
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO pgintel', current_database());
END
$$;

-- pg_monitor -> pg_read_all_stats provides access to statistics views.
-- No table DML privileges are granted to pgintel.
