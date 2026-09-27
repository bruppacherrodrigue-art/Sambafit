-- Refuse rollback if multiple indexed operations would collide.
DO $$ BEGIN
  IF EXISTS(SELECT 1 FROM operations WHERE operation_index <> 0) THEN
    RAISE EXCEPTION 'cannot drop operation_index while indexed operations exist';
  END IF;
END $$;
DROP INDEX operations_raw_index_idx;
ALTER TABLE operations DROP CONSTRAINT operations_raw_wallet_decoder_index_key;
ALTER TABLE operations DROP COLUMN operation_index;
ALTER TABLE operations ADD CONSTRAINT operations_raw_event_id_wallet_decoder_version_key
  UNIQUE(raw_event_id,wallet,decoder_version);
DELETE FROM schema_migrations WHERE version=5;
