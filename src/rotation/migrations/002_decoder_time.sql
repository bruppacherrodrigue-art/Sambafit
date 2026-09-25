ALTER TABLE operations ADD COLUMN decoded_at timestamptz NOT NULL DEFAULT now();
UPDATE operations o SET decoded_at=o.available_at
FROM raw_events r WHERE r.id=o.raw_event_id AND r.dataset='DEMO';
CREATE INDEX operations_decoder_asof_idx ON operations(raw_event_id,wallet,decoded_at DESC,id DESC);
INSERT INTO schema_migrations(version) VALUES (2) ON CONFLICT DO NOTHING;
