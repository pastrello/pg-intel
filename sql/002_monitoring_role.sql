-- PG Intelligence - cluster-level monitoring role
-- Run ONCE per monitored PostgreSQL cluster as a PostgreSQL administrator.
-- Authentication/password is intentionally configured separately.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'pgintel') THEN
        CREATE ROLE pgintel LOGIN;
    END IF;
END
$$;

-- Harden the source-side role: observation only.
ALTER ROLE pgintel
    NOSUPERUSER
    NOCREATEDB
    NOCREATEROLE
    NOREPLICATION
    NOBYPASSRLS;

GRANT pg_monitor TO pgintel;

-- Extra guardrails. pgintel only executes SELECTs on the monitored side.
ALTER ROLE pgintel SET default_transaction_read_only = on;
ALTER ROLE pgintel SET statement_timeout = '15s';
ALTER ROLE pgintel SET lock_timeout = '2s';
ALTER ROLE pgintel SET idle_in_transaction_session_timeout = '30s';

COMMENT ON ROLE pgintel IS 'Read-only monitoring role for PG Intelligence';

-- Set authentication separately, preferably SCRAM/certificate/peer according
-- to your environment. Example (run manually, do not store the password here):
--   ALTER ROLE pgintel PASSWORD '...';
