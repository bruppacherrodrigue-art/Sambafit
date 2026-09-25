DROP INDEX IF EXISTS operations_decoder_asof_idx;
ALTER TABLE operations DROP COLUMN IF EXISTS decoded_at;
DELETE FROM schema_migrations WHERE version=2;
