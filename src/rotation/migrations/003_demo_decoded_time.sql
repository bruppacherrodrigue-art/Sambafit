UPDATE operations o SET decoded_at=o.available_at
FROM raw_events r WHERE r.id=o.raw_event_id AND r.dataset='DEMO' AND o.decoded_at>o.available_at;
INSERT INTO schema_migrations(version) VALUES (3) ON CONFLICT DO NOTHING;
