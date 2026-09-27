CREATE TABLE research_classifications(
  id bigserial PRIMARY KEY,
  version text NOT NULL,
  network text NOT NULL CHECK(network='solana'),
  mint text NOT NULL,
  symbol text NOT NULL,
  category text NOT NULL,
  study_role text NOT NULL,
  status text NOT NULL CHECK(status IN ('research_candidate','admitted','excluded','uncertain')),
  known_at timestamptz NOT NULL,
  effective_from timestamptz NOT NULL,
  proof_at timestamptz NOT NULL,
  proof jsonb NOT NULL,
  reason text NOT NULL,
  UNIQUE(version,network,mint)
);
CREATE INDEX research_classifications_time_idx ON research_classifications(network,mint,known_at,effective_from);
INSERT INTO schema_migrations(version) VALUES (4) ON CONFLICT DO NOTHING;
