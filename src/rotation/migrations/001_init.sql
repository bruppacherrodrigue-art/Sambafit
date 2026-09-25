CREATE TABLE IF NOT EXISTS schema_migrations(version integer PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now());

CREATE TABLE tokens(
  id bigserial PRIMARY KEY, network text NOT NULL CHECK(network='solana'), mint text NOT NULL,
  symbol text, decimals smallint NOT NULL CHECK(decimals BETWEEN 0 AND 18), metadata jsonb NOT NULL DEFAULT '{}',
  discovered_at timestamptz NOT NULL DEFAULT now(), active boolean NOT NULL DEFAULT true,
  exclusion_reason text, UNIQUE(network,mint));
CREATE TABLE watchlist_versions(
  id bigserial PRIMARY KEY, content_hash text NOT NULL UNIQUE, known_at timestamptz NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(), payload jsonb NOT NULL);
CREATE TABLE watchlist_members(
  version_id bigint NOT NULL REFERENCES watchlist_versions(id), token_id bigint NOT NULL REFERENCES tokens(id),
  eligible_from timestamptz NOT NULL, eligible_until timestamptz, status text NOT NULL DEFAULT 'active',
  PRIMARY KEY(version_id,token_id), CHECK(eligible_until IS NULL OR eligible_until > eligible_from));
CREATE TABLE profiles(id bigserial PRIMARY KEY, platform text NOT NULL, handle text NOT NULL,
  source_url text, discovered_at timestamptz NOT NULL DEFAULT now(), UNIQUE(platform,handle));
CREATE TABLE wallets(
  address text PRIMARY KEY, network text NOT NULL DEFAULT 'solana', category text NOT NULL DEFAULT 'unknown',
  category_reason text, first_known_at timestamptz NOT NULL DEFAULT now(), observed_coverage numeric(8,5),
  CHECK(category IN ('unknown','directional','pool','router','exchange','market_maker','arbitrage')));
CREATE TABLE wallet_profile_links(
  id bigserial PRIMARY KEY, wallet text NOT NULL REFERENCES wallets(address), profile_id bigint NOT NULL REFERENCES profiles(id),
  proof text NOT NULL, verified_at timestamptz NOT NULL, confidence text NOT NULL,
  UNIQUE(wallet,profile_id,proof));
CREATE TABLE wallet_relations(
  id bigserial PRIMARY KEY, wallet_a text NOT NULL REFERENCES wallets(address), wallet_b text NOT NULL REFERENCES wallets(address),
  reason text NOT NULL, proof text NOT NULL, confidence text NOT NULL, known_at timestamptz NOT NULL,
  CHECK(wallet_a <> wallet_b), UNIQUE(wallet_a,wallet_b,reason,proof));
CREATE TABLE cohort_versions(
  id bigserial PRIMARY KEY, content_hash text NOT NULL UNIQUE, known_at timestamptz NOT NULL,
  valid_from timestamptz NOT NULL, payload jsonb NOT NULL);
CREATE TABLE cohort_members(version_id bigint REFERENCES cohort_versions(id), wallet text REFERENCES wallets(address),
  entity_group text, weight numeric(12,8) NOT NULL CHECK(weight>=0 AND weight<=1),
  PRIMARY KEY(version_id,wallet));
CREATE TABLE raw_events(
  id bigserial PRIMARY KEY, network text NOT NULL DEFAULT 'solana', signature text NOT NULL, wallet text NOT NULL,
  dataset text NOT NULL DEFAULT 'REAL' CHECK(dataset IN ('REAL','DEMO')),
  slot bigint, block_time timestamptz, first_seen_at timestamptz NOT NULL DEFAULT now(),
  ingested_at timestamptz NOT NULL DEFAULT now(), source text NOT NULL, parser_version text NOT NULL,
  response_hash text NOT NULL, payload jsonb NOT NULL, UNIQUE(network,signature,wallet,dataset));
CREATE INDEX raw_events_time_idx ON raw_events(block_time,first_seen_at);
CREATE TABLE operations(
  id bigserial PRIMARY KEY, raw_event_id bigint NOT NULL REFERENCES raw_events(id), wallet text NOT NULL,
  economic_at timestamptz NOT NULL, available_at timestamptz NOT NULL, kind text NOT NULL,
  status text NOT NULL, quality text NOT NULL, fee_lamports bigint NOT NULL DEFAULT 0,
  legs jsonb NOT NULL, decoder_version text NOT NULL, UNIQUE(raw_event_id,wallet,decoder_version));
CREATE INDEX operations_available_idx ON operations(available_at,wallet);
CREATE TABLE market_bars(
  id bigserial PRIMARY KEY, mint text NOT NULL, close_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL, price_usd numeric(38,18) NOT NULL CHECK(price_usd>0),
  volume_usd numeric(38,18), liquidity_usd numeric(38,18), source text NOT NULL,
  source_version text NOT NULL, dataset text NOT NULL CHECK(dataset IN ('REAL','DEMO')),
  raw_hash text, UNIQUE(mint,close_at,available_at,source,dataset));
CREATE INDEX market_bars_asof_idx ON market_bars(mint,available_at,close_at);
CREATE TABLE observed_inventories(
  id bigserial PRIMARY KEY, wallet text NOT NULL, mint text NOT NULL, observed_at timestamptz NOT NULL,
  available_at timestamptz NOT NULL, amount_base numeric(78,0) NOT NULL,
  coverage numeric(8,5), source_event_id bigint REFERENCES raw_events(id), UNIQUE(wallet,mint,observed_at));
CREATE TABLE rotations(
  id bigserial PRIMARY KEY, source_mint text NOT NULL, destination_mint text, evidence text NOT NULL
    CHECK(evidence IN ('direct','inferred','aggregate')), direction text NOT NULL,
  amount_usd numeric(38,18) NOT NULL CHECK(amount_usd>0), wallet text, source_operation_id text,
  destination_operation_id text, economic_at timestamptz NOT NULL, available_at timestamptz NOT NULL,
  dataset text NOT NULL CHECK(dataset IN ('REAL','DEMO')), source_hash text NOT NULL,
  UNIQUE(source_hash,dataset));
CREATE INDEX rotations_available_idx ON rotations(dataset,available_at);
CREATE TABLE rotation_attributions(
  rotation_id bigint NOT NULL REFERENCES rotations(id), source_operation_id text NOT NULL,
  destination_operation_id text, amount_usd numeric(38,18) NOT NULL CHECK(amount_usd>0),
  PRIMARY KEY(rotation_id,source_operation_id,destination_operation_id));
CREATE TABLE feature_snapshots(
  id bigserial PRIMARY KEY, pair text NOT NULL, decision_at timestamptz NOT NULL,
  config_hash text NOT NULL, payload jsonb NOT NULL, source_ids jsonb NOT NULL, dataset text NOT NULL,
  UNIQUE(pair,decision_at,config_hash,dataset));
CREATE TABLE signal_revisions(
  id bigserial PRIMARY KEY, pair text NOT NULL, decision_at timestamptz NOT NULL,
  state text NOT NULL CHECK(state IN ('observing','candidate','confirmed','invalidated','expired')),
  quality text NOT NULL, score integer NOT NULL CHECK(score BETWEEN 0 AND 100),
  components jsonb NOT NULL, reasons jsonb NOT NULL DEFAULT '[]', config_hash text NOT NULL,
  dataset text NOT NULL CHECK(dataset IN ('REAL','DEMO','REPLAY','PAPER LIVE')),
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE(pair,decision_at,state,config_hash,dataset));
CREATE INDEX signal_revisions_time_idx ON signal_revisions(dataset,decision_at);
CREATE TABLE alerts(id bigserial PRIMARY KEY, revision_id bigint NOT NULL UNIQUE REFERENCES signal_revisions(id),
  created_at timestamptz NOT NULL DEFAULT now(), acknowledged_at timestamptz);
CREATE TABLE experiments(id uuid PRIMARY KEY, config_hash text NOT NULL, dataset text NOT NULL,
  started_at timestamptz NOT NULL, ended_at timestamptz, status text NOT NULL, result jsonb NOT NULL DEFAULT '{}');
CREATE TABLE paper_portfolios(id uuid PRIMARY KEY, experiment_id uuid REFERENCES experiments(id),
  initial_cash numeric(38,18) NOT NULL, cash numeric(38,18) NOT NULL,
  holdings jsonb NOT NULL DEFAULT '{}', fees numeric(38,18) NOT NULL DEFAULT 0,
  updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE paper_orders(id text PRIMARY KEY, portfolio_id uuid NOT NULL REFERENCES paper_portfolios(id),
  signal_revision_id bigint REFERENCES signal_revisions(id), mint text NOT NULL, side text NOT NULL,
  quantity numeric(38,18) NOT NULL, status text NOT NULL, intended_at timestamptz NOT NULL,
  filled_at timestamptz, price numeric(38,18), fee numeric(38,18));
CREATE TABLE jobs(id uuid PRIMARY KEY, kind text NOT NULL, dataset text NOT NULL, status text NOT NULL,
  config_hash text NOT NULL, progress jsonb NOT NULL DEFAULT '{}', max_calls integer NOT NULL,
  calls_used integer NOT NULL DEFAULT 0, stop_requested boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE checkpoints(wallet text PRIMARY KEY, cursor text, pages integer NOT NULL DEFAULT 0,
  coverage text NOT NULL, updated_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE coverage_gaps(id bigserial PRIMARY KEY, wallet text, start_at timestamptz, end_at timestamptz,
  reason text NOT NULL, detected_at timestamptz NOT NULL DEFAULT now(), resolved_at timestamptz);
INSERT INTO schema_migrations(version) VALUES (1) ON CONFLICT DO NOTHING;
