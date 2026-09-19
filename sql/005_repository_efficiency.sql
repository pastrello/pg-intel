-- PG Intelligence 0.1.6 - repository efficiency metrics
-- Apply to the PG Intelligence repository, never to the monitored application database.
-- Safe/idempotent: only adds missing collection-cycle accounting columns.

ALTER TABLE pgintel.collection_cycles
    ADD COLUMN IF NOT EXISTS table_rows_stored integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS index_rows_stored integer NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS events_suppressed integer NOT NULL DEFAULT 0;
