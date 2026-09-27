-- A transaction may contain several economic operations for the same actor.
ALTER TABLE operations ADD COLUMN operation_index integer NOT NULL DEFAULT 0
  CHECK (operation_index >= 0);
ALTER TABLE operations DROP CONSTRAINT operations_raw_event_id_wallet_decoder_version_key;
ALTER TABLE operations ADD CONSTRAINT operations_raw_wallet_decoder_index_key
  UNIQUE(raw_event_id,wallet,decoder_version,operation_index);
CREATE INDEX operations_raw_index_idx ON operations(raw_event_id,wallet,operation_index,decoded_at DESC);
INSERT INTO schema_migrations(version) VALUES (5) ON CONFLICT DO NOTHING;
