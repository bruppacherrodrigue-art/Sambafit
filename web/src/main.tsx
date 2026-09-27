import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'
import R3Panel from './R3Panel'

type Dataset = 'DEMO' | 'REAL' | 'REPLAY'
type Tab = 'Vue générale' | 'Opérations' | 'Flux et signaux' | 'Marché' | 'Expériences' | 'R2 réel' | 'R3 réel' | 'Configuration'
type Overview = { dataset: Dataset; wallets: number; tokens: number; raw_events: number; operations: number; market_bars: number; signals: number; open_gaps: number }
type Signal = { pair: string; decision_at: string; state: string; quality: string; score: number; components: Record<string, number>; reasons: string[]; config_hash: string; dataset: string }
type Rotation = { source: string; destination: string | null; evidence: string; direction: string; amount_usd: string; wallet: string; source_op: string; destination_op: string | null; economic_at: string; available_at: string }
type AggregateFlow = { source: string; destination: string; evidence: 'aggregate'; amount_usd: string; seller_entities: number; buyer_entities: number; concentration: string; independence_uncertain: boolean; available_at: string }
type Bar = { mint: string; close_at: string; available_at: string; price_usd: string; volume_usd: string; liquidity_usd: string | null; source: string; dataset: string }
type Wallet = { address: string; category: string; fomo_profile: string | null; proof: string | null; confidence: string | null }
type Token = { mint: string; symbol: string | null; decimals: number; active: boolean }
type Experiment = { id: string; dataset: string; status: string; config_hash: string; result: Record<string, unknown>; started_at: string }
type Coverage = { checkpoints: Array<Record<string, unknown>>; gaps: Array<Record<string, unknown>>; note?: string }
type Operation = { signature: string; wallet: string; kind: string; quality: string; status: string; fee_lamports: number; decoder_version: string; economic_at: string; available_at: string; decoded_at: string; legs: Array<{ mint: string; delta_base: string; decimals: number; usd_price: string | null }> }
type Evidence = { raw: { signature: string; wallet: string; slot: number; block_time: string; first_seen_at: string; ingested_at: string; source: string; parser_version: string; response_hash: string; dataset: string; payload: Record<string, unknown> }; operation: Operation | null }
type OperationContext = { rotations: Rotation[]; market_features: Record<string, { last_price: string | null; last_close_at: string | null; liquidity_usd: string | null }>; decision: { state: string; quality: string; reasons: string[] }; note: string }
type R2Candidate = { symbol: string; mint: string; status: string; reasons: string[]; primary_pool: string; dex: string; reserve_usd_snapshot: string | null; rolling_h24_volume_usd: string | null; closed_daily_candles: number; known_at: string }
type R2Wallet = { wallet: string; provenance: string; swaps: number; observed_usd: string; attributed_between_coins_usd: string; first_at: string; last_at: string; signatures: string[]; uncertainty: string }
type R2Allocation = { wallet: string; source_mint: string; destination_mint: string; reserve_mint: string; amount_usd: string; source_signature: string; destination_signature: string; economic_at: string; available_at: string; warning: string }
type R2Budget = { limits: { max_calls: number; max_active_seconds: number }; calls_used: number; active_seconds: number; errors: Array<Record<string, unknown>> }
type R2Follow = { stop_reason: string; wallets: Record<string, { seen: string[]; last_checked_at: string | null; coverage_started_at?: string }>; transactions: Record<string, { kind: string; quality: string; usd_value: string | null }>; market_snapshots: Array<{ mint: string; received_at: string; price_usd: string | null; rolling_h24_volume_usd: string | null; reserve_usd_snapshot: string | null }>; gaps: Array<Record<string, unknown>>; opening_positions_unknown?: boolean; observable_inventory_delta_base?: Record<string, Record<string, string>> }

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${path}`)
  return response.json() as Promise<T>
}
const fmt = (value: number, digits = 0) => new Intl.NumberFormat('fr-CH', { maximumFractionDigits: digits }).format(value)
const time = (value?: string | null) => value ? new Date(value).toLocaleString('fr-CH', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC' : '—'
const stateName: Record<string, string> = { observing: 'Observation', candidate: 'Candidate', confirmed: 'Confirmée', invalidated: 'Invalidée', expired: 'Expirée' }

function LineChart({ bars, title, events }: { bars: Bar[]; title: string; events?: Signal[] }) {
  if (bars.length < 2) return <div className="empty">Aucune série complète pour {title}.</div>
  const values = bars.map(b => Number(b.price_usd))
  const min = Math.min(...values), max = Math.max(...values), span = max - min || 1
  const x = (i: number) => 26 + i * 650 / (bars.length - 1)
  const y = (v: number) => 190 - (v - min) * 150 / span
  const path = values.map((v, i) => `${i === 0 ? 'M' : 'L'} ${x(i)} ${y(v)}`).join(' ')
  const markers = (events || []).filter(e => bars.some(b => b.close_at === e.decision_at))
  return <div className="chart-wrap"><div className="chart-head"><strong>{title}</strong><span>{fmt(values[values.length - 1], 4)} · {bars[0].source}</span></div>
    <svg viewBox="0 0 700 225" role="img" aria-label={`Graphique ${title}`}>
      {[40, 115, 190].map(yy => <line key={yy} x1="26" y1={yy} x2="676" y2={yy} className="gridline" />)}
      <path d={path} className="price-line" />
      {markers.map((event, index) => { const i = bars.findIndex(b => b.close_at === event.decision_at); return <g key={`${event.state}-${index}`}>
        <line x1={x(i)} y1="24" x2={x(i)} y2="190" className="event-line" />
        <circle cx={x(i)} cy={y(values[i])} r="5" className={`event-dot ${event.state}`} />
      </g> })}
      <text x="26" y="217">{time(bars[0].close_at)}</text><text x="550" y="217">{time(bars[bars.length - 1].close_at)}</text>
    </svg></div>
}

function download(name: string, value: unknown, csv = false) {
  const body = csv && Array.isArray(value) && value.length
    ? [Object.keys(value[0]).join(','), ...value.map(row => Object.values(row).map(cell => `"${String(cell ?? '').replaceAll('"', '""')}"`).join(','))].join('\n')
    : JSON.stringify(value, null, 2)
  const url = URL.createObjectURL(new Blob([body], { type: csv ? 'text/csv' : 'application/json' }))
  const a = document.createElement('a'); a.href = url; a.download = name; a.click(); URL.revokeObjectURL(url)
}

function App() {
  const [dataset, setDataset] = useState<Dataset>('DEMO')
  const [tab, setTab] = useState<Tab>('Vue générale')
  const [overview, setOverview] = useState<Overview | null>(null)
  const [signals, setSignals] = useState<Signal[]>([])
  const [rotations, setRotations] = useState<Rotation[]>([])
  const [aggregateFlows, setAggregateFlows] = useState<AggregateFlow[]>([])
  const [operations, setOperations] = useState<Operation[]>([])
  const [wallets, setWallets] = useState<Wallet[]>([])
  const [tokens, setTokens] = useState<Token[]>([])
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [sourceBars, setSourceBars] = useState<Bar[]>([])
  const [destBars, setDestBars] = useState<Bar[]>([])
  const [selected, setSelected] = useState<Signal | null>(null)
  const [evidence, setEvidence] = useState<Record<string, unknown> | null>(null)
  const [selectedOperation, setSelectedOperation] = useState<Operation | null>(null)
  const [operationEvidence, setOperationEvidence] = useState<Evidence | null>(null)
  const [operationContext, setOperationContext] = useState<OperationContext | null>(null)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('[\n  {\n    "network": "solana",\n    "mint": "",\n    "symbol": "",\n    "decimals": 6,\n    "eligible_from": "2026-09-25T00:00:00Z"\n  }\n]')
  const [importKind, setImportKind] = useState<'watchlist' | 'wallets'>('watchlist')
  const [message, setMessage] = useState('')
  const [r2Universe, setR2Universe] = useState<R2Candidate[]>([])
  const [r2Wallets, setR2Wallets] = useState<R2Wallet[]>([])
  const [r2PerCoin, setR2PerCoin] = useState<Record<string, Array<{ wallet: string; buys_usd: string; sells_usd: string; swaps: string }>>>({})
  const [r2Allocations, setR2Allocations] = useState<R2Allocation[]>([])
  const [r2Budget, setR2Budget] = useState<R2Budget | null>(null)
  const [r2Follow, setR2Follow] = useState<R2Follow | null>(null)
  const [r2Evidence, setR2Evidence] = useState<Record<string, unknown> | null>(null)
  const [r2Bars, setR2Bars] = useState<[Bar[], Bar[]]>([[], []])
  const [r2Proofs, setR2Proofs] = useState<Array<Record<string, unknown>>>([])
  const [r2Message, setR2Message] = useState('')
  const [proof, setProof] = useState({ profile: '', network: 'solana', address: '', proof_type: 'public_profile_explicit_address', proof_reference: '', verified_at: new Date().toISOString(), verified_by: '', status: 'proposed', comment: '' })

  useEffect(() => {
    Promise.all([get<{ records: R2Candidate[] }>('/api/r2/universe'), get<{ wallets: R2Wallet[]; per_coin_ranking: Record<string, Array<{ wallet: string; buys_usd: string; sells_usd: string; swaps: string }>> }>('/api/r2/cohort'),
      get<{ allocations: R2Allocation[] }>('/api/r2/sequences'), get<R2Budget>('/api/r2/budget'), get<Array<Record<string, unknown>>>('/api/r2/fomo-proofs'), get<R2Follow>('/api/r2/follow').catch(() => null)])
      .then(([u, c, s, b, p, f]) => { setR2Universe(u.records); setR2Wallets(c.wallets); setR2PerCoin(c.per_coin_ranking); setR2Allocations(s.allocations); setR2Budget(b); setR2Proofs(p); setR2Follow(f) })
      .catch(() => setR2Message('Corpus R2 indisponible sur cette API locale.'))
  }, [])
  useEffect(() => {
    const selected = r2Allocations[0]
    if (!selected) return
    Promise.all([get<Bar[]>(`/api/r2/market/${selected.source_mint}`), get<Bar[]>(`/api/r2/market/${selected.destination_mint}`)])
      .then(([a, b]) => setR2Bars([a, b])).catch(() => setR2Bars([[], []]))
  }, [r2Allocations])

  useEffect(() => {
    let mounted = true
    const q = `?dataset=${encodeURIComponent(dataset)}`
    const sourceQ = `?dataset=${dataset === 'REPLAY' ? 'REAL' : dataset}`
    Promise.all([get<Overview>('/api/overview' + q), get<Signal[]>('/api/signals' + q),
      get<Rotation[]>('/api/rotations' + sourceQ), get<AggregateFlow[]>('/api/aggregate-flows' + sourceQ), get<Operation[]>('/api/operations' + sourceQ),
      get<Wallet[]>('/api/wallets' + q), get<Token[]>('/api/tokens' + q),
      get<Experiment[]>('/api/experiments' + sourceQ), get<Coverage>('/api/coverage' + sourceQ)])
      .then(([o, s, r, ag, ops, w, t, ex, c]) => { if (mounted) { setOverview(o); setSignals(s); setRotations(r); setAggregateFlows(ag); setOperations(ops); setSelectedOperation(null); setWallets(w); setTokens(t); setExperiments(ex); setCoverage(c); setSelected(s[0] || null); setError('') } })
      .catch(e => mounted && setError(`API locale indisponible : ${e.message}`))
    return () => { mounted = false }
  }, [dataset])

  const pair = selected?.pair || rotations[0] && `${rotations[0].source}:${rotations[0].destination}` || (dataset === 'DEMO' ? 'DEMO-A:DEMO-B' : '')
  const [source, destination] = pair.split(':')
  useEffect(() => {
    if (!source || !destination) { setSourceBars([]); setDestBars([]); return }
    const sourceDataset = dataset === 'REPLAY' ? 'REAL' : dataset
    Promise.all([get<Bar[]>(`/api/market/${encodeURIComponent(source)}?dataset=${sourceDataset}`),
      get<Bar[]>(`/api/market/${encodeURIComponent(destination)}?dataset=${sourceDataset}`)])
      .then(([a, b]) => { setSourceBars(a); setDestBars(b) }).catch(() => { setSourceBars([]); setDestBars([]) })
  }, [source, destination, dataset])
  useEffect(() => {
    const related = rotations.find(r => `${r.source}:${r.destination}` === selected?.pair)
    if (!related) { setEvidence(null); return }
    get<Record<string, unknown>>(`/api/evidence/${encodeURIComponent(related.source_op)}?dataset=${dataset === 'REPLAY' ? 'REAL' : dataset}&wallet=${encodeURIComponent(related.wallet)}`)
      .then(setEvidence).catch(() => setEvidence(null))
  }, [selected, rotations, dataset])
  useEffect(() => {
    if (!selectedOperation) { setOperationEvidence(null); setOperationContext(null); return }
    const sourceDataset = dataset === 'REPLAY' ? 'REAL' : dataset
    const query = `?dataset=${sourceDataset}&wallet=${encodeURIComponent(selectedOperation.wallet)}`
    get<Evidence>(`/api/evidence/${encodeURIComponent(selectedOperation.signature)}${query}`)
      .then(setOperationEvidence).catch(() => setOperationEvidence(null))
    get<OperationContext>(`/api/operation-context/${encodeURIComponent(selectedOperation.signature)}${query}`)
      .then(setOperationContext).catch(() => setOperationContext(null))
  }, [selectedOperation, dataset])

  const ratioBars = useMemo(() => {
    const a = new Map(sourceBars.map(b => [b.close_at, Number(b.price_usd)]))
    return destBars.filter(b => a.has(b.close_at) && a.get(b.close_at)! > 0)
      .map(b => ({ ...b, price_usd: String(Number(b.price_usd) / a.get(b.close_at)!) }))
  }, [sourceBars, destBars])
  const r2RatioBars = useMemo(() => {
    const a = new Map(r2Bars[0].map(b => [b.close_at, Number(b.price_usd)]))
    return r2Bars[1].filter(b => a.has(b.close_at) && a.get(b.close_at)! > 0)
      .map(b => ({ ...b, price_usd: String(Number(b.price_usd) / a.get(b.close_at)!) }))
  }, [r2Bars])
  const ranking = useMemo(() => Object.entries(rotations.reduce<Record<string, { usd: number; count: number; direct: number }>>((acc, r) => {
    const item = acc[r.wallet] || { usd: 0, count: 0, direct: 0 }
    item.usd += Number(r.amount_usd); item.count += 1; item.direct += Number(r.evidence === 'direct'); acc[r.wallet] = item; return acc
  }, {})).sort((a, b) => b[1].usd - a[1].usd), [rotations])
  const tabs: Tab[] = ['Vue générale', 'Opérations', 'Flux et signaux', 'Marché', 'Expériences', 'R2 réel', 'R3 réel', 'Configuration']
  const displayedDataset: Dataset = tab === 'R2 réel' || tab === 'R3 réel' ? 'REAL' : dataset

  async function submitProof(event: React.FormEvent) {
    event.preventDefault()
    const response = await fetch('/api/r2/fomo-proofs', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(proof) })
    const value = await response.json()
    setR2Message(response.ok ? 'Preuve reçue : en attente de revue explicite.' : JSON.stringify(value))
    if (response.ok) setR2Proofs(await get('/api/r2/fomo-proofs'))
  }

  async function submitImport() {
    try {
      const entries = JSON.parse(draft)
      if (!Array.isArray(entries)) throw new Error('Un tableau JSON est attendu.')
      const response = await fetch(importKind === 'watchlist' ? '/api/watchlists' : '/api/wallets', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(importKind === 'watchlist' ? { known_at: new Date().toISOString(), entries } : { entries })
      })
      const result = await response.json()
      if (!response.ok) throw new Error(JSON.stringify(result))
      setMessage(`${entries.length} entrée(s) importée(s). Rechargez les données pour actualiser la vue.`)
    } catch (e) { setMessage(e instanceof Error ? e.message : String(e)) }
  }

  return <div className="app">
    <header className="topbar"><div className="brand"><div className="brand-mark">↗</div><div><strong>ROTATION</strong><small>RESEARCH ENGINE</small></div></div>
      <div className="top-actions"><span className="local-pill">● LOCAL / PRIVÉ</span><span className={`mode-pill ${displayedDataset.toLowerCase()}`}>{displayedDataset === 'DEMO' ? 'DEMO · SYNTHÉTIQUE' : displayedDataset === 'REPLAY' ? 'REPLAY · HISTORIQUE' : 'RECHERCHE · RÉEL'}</span></div></header>
    <main className="main"><section className="intro"><div><div className="eyebrow">SOLANA · ANALYSE DES FLUX</div><h1>Observer les rotations,<br/><em>vérifier les preuves.</em></h1><p>Décisions déterministes à partir des flux attribués, du marché disponible et de leur qualité. Aucun ordre réel.</p></div><div className="mode-switch"><label>JEU DE DONNÉES</label><button className={displayedDataset === 'DEMO' ? 'active' : ''} onClick={() => { setDataset('DEMO'); if (tab === 'R2 réel' || tab === 'R3 réel') setTab('Vue générale') }}>Démo</button><button className={displayedDataset === 'REAL' ? 'active' : ''} onClick={() => setDataset('REAL')}>Réel</button><button className={displayedDataset === 'REPLAY' ? 'active' : ''} onClick={() => { setDataset('REPLAY'); if (tab === 'R2 réel' || tab === 'R3 réel') setTab('Vue générale') }}>Replay</button></div></section>
      {error && <div className="error-box">{error}<br/><code>rotation doctor</code> puis démarrez l’API locale.</div>}
      <div className="disclosure"><strong>{displayedDataset === 'DEMO' ? 'Scénario synthétique' : 'Données réelles non qualifiées'}</strong><span>{displayedDataset === 'DEMO' ? 'Les wallets, mints, prix et résultats de cette vue sont fictifs. Ils démontrent le logiciel, pas une stratégie.' : 'Aucun signal ne vaut preuve d’avantage financier. La couverture des comptes et la liquidité historique restent à qualifier.'}</span></div>
      <nav className="tabs">{tabs.map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => { setTab(t); if (t === 'R2 réel' || t === 'R3 réel') setDataset('REAL') }}>{t}</button>)}</nav>

      {tab === 'Vue générale' && <><div className="metric-grid">
        <article className="metric"><span>ÉVÉNEMENTS BRUTS</span><strong>{overview ? fmt(overview.raw_events) : '—'}</strong><small>{dataset === 'DEMO' ? 'fixture synthétique' : 'source RPC'}</small></article>
        <article className="metric"><span>OPÉRATIONS</span><strong>{overview ? fmt(overview.operations) : '—'}</strong><small>finalisées ou qualité explicitée</small></article>
        <article className="metric"><span>SIGNAUX</span><strong>{overview ? fmt(overview.signals) : '—'}</strong><small>révisions persistées</small></article>
        <article className="metric"><span>TROUS OUVERTS</span><strong>{overview ? fmt(overview.open_gaps) : '—'}</strong><small>couverture réelle séparée</small></article>
      </div><div className="two-col"><section className="panel"><div className="section-head"><div><span className="eyebrow">QUALITÉ</span><h2>État de la collecte</h2></div><span className="subtle">{dataset}</span></div>
        <div className="quality-row"><span>Wallets enregistrés</span><strong>{overview?.wallets ?? '—'}</strong></div><div className="quality-row"><span>Tokens surveillés</span><strong>{overview?.tokens ?? '—'}</strong></div><div className="quality-row"><span>Bougies disponibles</span><strong>{overview?.market_bars ?? '—'}</strong></div><div className="quality-row"><span>Dernière opération disponible</span><strong>{time(operations.at(-1)?.available_at)}</strong></div>
        <div className="note">{coverage?.note || (coverage?.gaps.length ? `${coverage.gaps.length} trou(s) de collecte demandent vérification.` : 'Aucun trou enregistré. Cela ne prouve pas une couverture complète des comptes de tokens fermés.')}</div></section>
        <section className="panel"><div className="section-head"><div><span className="eyebrow">DÉCISIONS</span><h2>Chronologie récente</h2></div><button className="text-button" onClick={() => setTab('Flux et signaux')}>Voir les preuves →</button></div>{signals.length ? signals.slice(-5).reverse().map((s, i) => <button key={`${s.pair}-${i}`} className="timeline-item" onClick={() => { setSelected(s); setTab('Flux et signaux') }}><span className={`state-dot ${s.state}`}></span><span><strong>{s.pair}</strong><small>{time(s.decision_at)} · {s.quality}</small></span><b>{stateName[s.state] || s.state}</b></button>) : <div className="empty">Aucun signal enregistré dans ce jeu de données.</div>}</section></div></>}

      {tab === 'Opérations' && <div className="two-col flow-layout"><section className="panel"><div className="section-head"><div><span className="eyebrow">{dataset} · RPC FINALISÉ</span><h2>Opérations observées</h2></div><button className="text-button" onClick={() => download(`operations-${dataset}.json`, operations)}>Exporter JSON ↗</button></div><p className="muted">Un wallet affiché ici est une adresse on-chain non attribuée à Fomo sauf preuve datée dans son registre. Les transactions partielles ne créent pas de flux exécutable.</p>{operations.length ? <div className="operation-list">{operations.map(op => <button key={`${op.signature}:${op.wallet}`} className={`operation-row ${selectedOperation?.signature === op.signature ? 'selected' : ''}`} onClick={() => setSelectedOperation(op)}><span><strong>{op.signature.slice(0, 14)}…</strong><small>{time(op.economic_at)} → disponible {time(op.available_at)}</small></span><span className={`evidence-pill ${op.quality === 'complete' ? 'direct' : 'inferred'}`}>{op.kind} · {op.quality}</span></button>)}</div> : <div className="empty">Aucune opération dans ce jeu de données.</div>}</section><section className="panel evidence-panel"><div className="section-head"><div><span className="eyebrow">PREUVE ET CHRONOLOGIE</span><h2>{selectedOperation ? `${selectedOperation.signature.slice(0, 12)}…` : 'Choisir une opération'}</h2></div></div>{selectedOperation ? <><div className="quality-row"><span>Jeu / provenance</span><strong>{dataset} · {operationEvidence?.raw.source || 'chargement'}</strong></div><div className="quality-row"><span>Wallet observé</span><strong className="mono small">{selectedOperation.wallet}</strong></div><div className="quality-row"><span>Attribution Fomo</span><strong>{wallets.find(w => w.address === selectedOperation.wallet)?.fomo_profile || 'Aucune preuve'}</strong></div><div className="quality-row"><span>Bloc / première réception</span><strong>{time(selectedOperation.economic_at)} / {time(operationEvidence?.raw.first_seen_at)}</strong></div><div className="quality-row"><span>Disponible / décodé</span><strong>{time(selectedOperation.available_at)} / {time(selectedOperation.decoded_at)}</strong></div><div className="quality-row"><span>Slot / frais réseau</span><strong>{operationEvidence?.raw.slot ?? '—'} / {selectedOperation.fee_lamports} lamports</strong></div><div className="quality-row"><span>Qualité / version</span><strong>{selectedOperation.quality} · {selectedOperation.decoder_version}</strong></div><h3>Variations des comptes du wallet</h3>{selectedOperation.legs.length ? selectedOperation.legs.map((leg, i) => <div className="quality-row" key={`${leg.mint}-${i}`}><span className="mono small">{leg.mint}</span><strong>{leg.delta_base} base · {leg.decimals} décimales</strong></div>) : <div className="empty">Aucune variation SPL attribuable.</div>}<h3>Marché, attribution et décision</h3>{operationContext ? <><p className="muted">{operationContext.rotations.length ? operationContext.rotations.map(r => `${r.evidence}: ${r.direction} ${r.source} → ${r.destination}`).join(' · ') : 'Aucune réallocation USD attribuable à cette opération.'}</p>{Object.entries(operationContext.market_features).map(([mint, f]) => <div className="quality-row" key={mint}><span className="mono small">{mint.slice(0, 12)}… · close {time(f.last_close_at)}</span><strong>{f.last_price ?? 'prix inconnu'} $ · liquidité {f.liquidity_usd ?? 'inconnue'}</strong></div>)}<div className="quality-row"><span>Décision</span><strong>{operationContext.decision.state} · {operationContext.decision.quality}</strong></div><p className="muted">{operationContext.note}</p></> : <p className="muted">Contexte non disponible.</p>}<p className="muted">Le payeur de frais, les signataires et le propriétaire des comptes sont distincts dans la réponse brute. Une jambe SOL native ou un compte fermé peut rester non attribué.</p>{operationEvidence && <details><summary>Réponse RPC, hash et opération normalisée</summary><pre>{JSON.stringify(operationEvidence, null, 2)}</pre></details>}</> : <div className="empty">Cliquez sur une transaction pour ouvrir sa preuve brute et ses deux horloges.</div>}</section></div>}

      {tab === 'Flux et signaux' && <><div className="two-col flow-layout"><section className="panel"><div className="section-head"><div><span className="eyebrow">ATTRIBUTION</span><h2>Flux entre coins</h2></div><button className="text-button" onClick={() => download(`rotations-${dataset}.json`, rotations)}>Exporter JSON ↗</button></div>
        {rotations.length ? <div className="table-wrap"><table><thead><tr><th>Origine → destination</th><th>Preuve</th><th>Montant attribué</th><th>Wallet</th></tr></thead><tbody>{rotations.map((r, i) => <tr key={i}><td><strong>{r.source} → {r.destination || 'inconnue'}</strong><small>{r.direction}</small></td><td><span className={`evidence-pill ${r.evidence}`}>{r.evidence}</span></td><td>{fmt(Number(r.amount_usd), 2)} $</td><td>{r.wallet}</td></tr>)}</tbody></table></div> : <div className="empty">Aucun flux attribuable. Un transfert ou un décodage partiel ne devient pas une rotation.</div>}</section>
        <section className="panel"><div className="section-head"><div><span className="eyebrow">ÉCHANTILLON BORNÉ</span><h2>Wallets candidats dans l’échantillon</h2></div></div><p className="muted">Classement par flux directionnels valorisés observés ici. Il ne représente pas les plus gros traders de Solana.</p>{ranking.length ? ranking.map(([wallet, item], i) => <div className="rank-row" key={wallet}><span className="rank-num">{String(i + 1).padStart(2, '0')}</span><div><strong>{wallet}</strong><small>{wallets.find(w => w.address === wallet)?.fomo_profile ? 'Profil Fomo avec preuve' : 'On-chain non attribué à Fomo'} · {item.count} attribution(s) · {item.direct} directe(s)</small></div><b>{fmt(item.usd)} $</b></div>) : <div className="empty">Aucun wallet classable. Le P&amp;L Fomo seul ne qualifie pas un gros trader.</div>}</section></div>
        <section className="panel"><div className="section-head"><div><span className="eyebrow">PREUVE AGRÉGÉE DISTINCTE</span><h2>Convergence des entités</h2></div><button className="text-button" onClick={() => download(`aggregats-${dataset}.json`, aggregateFlows)}>Exporter JSON ↗</button></div><p className="muted">Ces flux ne prouvent pas que les mêmes fonds ont quitté A pour B. Les liens inconnus entre wallets rendent l’indépendance incertaine.</p>{aggregateFlows.length ? <div className="table-wrap"><table><thead><tr><th>Paire</th><th>Vendeurs / acheteurs</th><th>Montant borné</th><th>Concentration</th></tr></thead><tbody>{aggregateFlows.map((flow, i) => <tr key={i}><td>{flow.source} → {flow.destination}</td><td>{flow.seller_entities} / {flow.buyer_entities}</td><td>{fmt(Number(flow.amount_usd), 2)} $</td><td>{fmt(Number(flow.concentration) * 100, 1)} %</td></tr>)}</tbody></table></div> : <div className="empty">Aucune convergence multi-entités vérifiable.</div>}</section>
        <div className="two-col"><section className="panel"><div className="section-head"><div><span className="eyebrow">MACHINE D’ÉTATS</span><h2>Révisions des signaux</h2></div><button className="text-button" onClick={() => download(`signaux-${dataset}.csv`, signals, true)}>Exporter CSV ↗</button></div>{signals.length ? signals.map((s, i) => <button key={i} className={`signal-row ${selected === s ? 'selected' : ''}`} onClick={() => setSelected(s)}><span className={`state-dot ${s.state}`}></span><div><strong>{s.pair}</strong><small>{time(s.decision_at)} · {s.quality}</small></div><b>{stateName[s.state] || s.state}</b><span className="score">{s.score}/100</span></button>) : <div className="empty">Aucune révision.</div>}</section>
        <section className="panel evidence-panel"><div className="section-head"><div><span className="eyebrow">POURQUOI / PREUVES</span><h2>{selected?.pair || 'Sélectionner un signal'}</h2></div>{selected && <span className={`state-label ${selected.state}`}>{stateName[selected.state] || selected.state}</span>}</div>
        {selected ? <><p className="muted">Score hypothétique {selected.score}/100. Ce score n’est pas une probabilité de réussite.</p><div className="component-list">{Object.entries(selected.components).map(([name, score]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><b>{score}</b></div>)}</div><h3>Raisons</h3><ul>{selected.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul><h3>Traçabilité</h3><p className="mono small">Config {selected.config_hash.slice(0, 18)}…<br/>Décision {time(selected.decision_at)}<br/>Qualité {selected.quality}<br/>Source {evidence ? String((evidence.raw as Record<string, unknown>).source) : 'indisponible'}</p>{evidence && <details><summary>Réponse brute et opération normalisée</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>}</> : <div className="empty">Cliquez sur une révision pour inspecter ses raisons.</div>}</section></div></>}

      {tab === 'Marché' && <><div className="market-title"><div><span className="eyebrow">CONTEXTE DISPONIBLE À LA DÉCISION</span><h2>{pair || 'Aucune paire sélectionnée'}</h2></div><span className="subtle">Prix de clôture · aucun prix futur dans la décision</span></div><div className="two-col"><section className="panel"><LineChart bars={destBars} title={`${destination || 'B'} / USD`} events={signals.filter(s => s.pair === pair)} /></section><section className="panel"><LineChart bars={ratioBars} title={`${destination || 'B'} / ${source || 'A'}`} events={signals.filter(s => s.pair === pair)} /></section></div><div className="note wide">Les marqueurs indiquent l’heure de disponibilité du signal. Les graphiques utilisent les bougies closes. Une quote historique exécutable n’est pas fournie par ces seules bougies.</div></>}

      {tab === 'Expériences' && <><div className="section-head standalone"><div><span className="eyebrow">REPLAY / PAPER</span><h2>Expériences enregistrées</h2></div></div>{experiments.length ? <div className="experiment-grid">{experiments.map(e => <article className="panel experiment" key={e.id}><div className="experiment-top"><span className="evidence-pill">{e.result.initial_cash ? 'PAPER' : 'REPLAY'}</span><span className="subtle">{time(e.started_at)}</span></div><h3>{e.result.initial_cash ? 'Portefeuille simulé' : 'Étude de signaux'}</h3><p>{e.result.synthetic ? 'Données synthétiques DEMO' : 'Données réelles non qualifiées'}</p><div className="quality-row"><span>Opérations simulées</span><strong>{String(e.result.filled_orders ?? e.result.rotations ?? '—')}</strong></div><div className="quality-row"><span>Cash final</span><strong>{String(e.result.ending_cash ?? '—')}</strong></div><div className="quality-row"><span>Avantage financier</span><strong>Non évalué</strong></div><details><summary>Rapport JSON et hypothèses</summary><pre>{JSON.stringify(e.result, null, 2)}</pre></details><small className="mono">{e.id}</small></article>)}</div> : <div className="panel empty">Aucune expérience. Exécutez <code>rotation replay</code> puis <code>rotation paper</code>.</div>}</>}

      {tab === 'R2 réel' && <><section className="panel"><span className="eyebrow">REAL · ÉCHANTILLON EXPLORATOIRE · 26.09.2026</span><h2>Univers de recherche et budget</h2><p className="muted">Proposition technique non approuvée comme watchlist. Réserves et volumes sont des relevés, sans profondeur historique exécutable. Les actifs de transit wSOL/USDC restent séparés.</p><div className="quality-row"><span>Appels R2 / plafond global</span><strong>{r2Budget ? `${r2Budget.calls_used} / ${r2Budget.limits.max_calls}` : '—'}</strong></div><div className="quality-row"><span>Collecte active / plafond</span><strong>{r2Budget ? `${fmt(r2Budget.active_seconds, 0)} / ${r2Budget.limits.max_active_seconds} s` : '—'}</strong></div><div className="table-wrap"><table><thead><tr><th>Coin et mint exact</th><th>Pool / programme</th><th>Réserve relevée</th><th>Volume glissant 24 h</th><th>Statut</th></tr></thead><tbody>{r2Universe.map(c => <tr key={c.mint}><td><strong>{c.symbol}</strong><br/><small className="mono">{c.mint}</small></td><td><small className="mono">{c.primary_pool}</small><br/>{c.dex}</td><td>{c.reserve_usd_snapshot ? `${fmt(Number(c.reserve_usd_snapshot))} $` : 'inconnu'}</td><td>{c.rolling_h24_volume_usd ? `${fmt(Number(c.rolling_h24_volume_usd))} $` : 'inconnu'}</td><td>{c.status}<br/><small>{c.reasons.join(', ') || `${c.closed_daily_candles} bougies quotidiennes closes`}</small></td></tr>)}</tbody></table></div><button className="button-secondary" onClick={() => download('r2-univers-reel.json', r2Universe)}>Exporter l’univers</button></section>
      <section className="panel"><span className="eyebrow">SUIVI BORNÉ · CHECKPOINT RÉEL</span><h2>Fraîcheur, positions observables et trous</h2><div className="quality-row"><span>Statut de collecte</span><strong>{r2Follow?.stop_reason || 'non lancée'}</strong></div><div className="quality-row"><span>Transactions supplémentaires / trous détectés</span><strong>{r2Follow ? Object.keys(r2Follow.transactions).length : '—'} / {r2Follow?.gaps.length ?? '—'}</strong></div><p className="muted">Positions avant le début de couverture : {r2Follow?.opening_positions_unknown ? 'inconnues' : 'non établies'}. Les deltas observables ne représentent pas le patrimoine total.</p>{r2Follow && Object.entries(r2Follow.wallets).map(([wallet, item]) => <div className="quality-row" key={wallet}><span className="mono">{wallet}</span><strong>{item.seen.length} signatures · depuis {time(item.coverage_started_at)} · dernier contrôle {time(item.last_checked_at)}</strong></div>)}<details><summary>Relevés de marché synchronisés, inventaire et trous</summary><pre>{JSON.stringify({ market_snapshots: r2Follow?.market_snapshots, observable_inventory_delta_base: r2Follow?.observable_inventory_delta_base, gaps: r2Follow?.gaps }, null, 2)}</pre></details></section>
      <div className="two-col"><section className="panel"><span className="eyebrow">COHORTE OBSERVÉE · NON ATTRIBUÉE À FOMO</span><h2>Wallets candidats dans l’échantillon</h2><p className="muted">USD estimé par trade du fournisseur, confirmé par les deux deltas SPL du propriétaire signataire. Couverture d’environ deux heures seulement ; sélection rétrospective biaisée.</p>{r2Wallets.map(w => <div className="rank-row" key={w.wallet}><div><strong className="mono">{w.wallet}</strong><small>{w.provenance} · {w.swaps} swaps · {time(w.first_at)} → {time(w.last_at)}</small><small>Réallocations inférées {fmt(Number(w.attributed_between_coins_usd), 2)} $ · durées de détention inconnues</small><button className="text-button" onClick={() => get<Record<string, unknown>>(`/api/r2/evidence/${w.signatures[0]}`).then(setR2Evidence)}>Ouvrir la preuve ↗</button></div><b>{fmt(Number(w.observed_usd), 2)} $</b></div>)}{!r2Wallets.length && <div className="empty">Aucun wallet attribuable dans cet échantillon.</div>}<button className="button-secondary" onClick={() => download('r2-cohorte-reelle.json', r2Wallets)}>Exporter la cohorte</button><details><summary>Classements par coin, couverture partielle</summary>{Object.entries(r2PerCoin).map(([mint, rows]) => <div key={mint}><h3>{r2Universe.find(c => c.mint === mint)?.symbol || mint}</h3>{rows.map(row => <div className="quality-row" key={row.wallet}><span className="mono">{row.wallet}</span><strong>{fmt(Number(row.buys_usd) + Number(row.sells_usd), 2)} $ · {row.swaps} swaps</strong></div>)}</div>)}</details></section>
      <section className="panel"><span className="eyebrow">SÉQUENCES LONGITUDINALES · INFÉRÉES VIA RÉSERVE</span><h2>Réallocations possibles</h2>{r2Allocations.map(a => <div className="signal-row" key={`${a.source_signature}:${a.destination_signature}`}><div><strong>{r2Universe.find(c => c.mint === a.source_mint)?.symbol || a.source_mint.slice(0, 7)} → {r2Universe.find(c => c.mint === a.destination_mint)?.symbol || a.destination_mint.slice(0, 7)}</strong><small>{time(a.economic_at)} · {a.wallet.slice(0, 9)}… · transit {a.reserve_mint.slice(0, 7)}…</small><small>Réception du backfill {time(a.available_at)} · fonds identiques non prouvés</small><button className="text-button" onClick={() => get<Record<string, unknown>>(`/api/r2/evidence/${a.source_signature}`).then(setR2Evidence)}>Vente et preuve ↗</button><button className="text-button" onClick={() => get<Record<string, unknown>>(`/api/r2/evidence/${a.destination_signature}`).then(setR2Evidence)}>Achat et preuve ↗</button></div><b>{fmt(Number(a.amount_usd), 2)} $</b></div>)}{!r2Allocations.length && <div className="empty">Zéro rotation dans le corpus disponible.</div>}<p className="muted">Aucun signal confirmé : couverture de marché au temps de décision insuffisante. Une quote historique exécutable et la profondeur passée sont absentes.</p></section></div>
      <div className="two-col"><section className="panel"><span className="eyebrow">PRIX ARCHIVÉS · PAS DE DÉCISION HISTORIQUE</span><h2>Contexte des deux premiers coins</h2><LineChart bars={r2Bars[0]} title="Source / USD" /><LineChart bars={r2Bars[1]} title="Destination / USD" /><LineChart bars={r2RatioBars} title="Ratio destination / source (clôtures quotidiennes)" /><p className="muted">Bougies quotidiennes closes, reçues lors du backfill. Le prix précis des opérations et le ratio à la minute peuvent manquer ; les volumes 24 h glissants ne sont pas additionnés.</p></section><section className="panel"><span className="eyebrow">PREUVE PUBLIQUE REAL</span><h2>Opération et chronologie</h2>{r2Evidence ? <><div className="quality-row"><span>Signature</span><strong className="mono">{String((r2Evidence.selection as Record<string, unknown>).signature)}</strong></div><div className="quality-row"><span>Décodage</span><strong>{String((r2Evidence.selection as Record<string, unknown>).decoded_kind)} · {String((r2Evidence.selection as Record<string, unknown>).decode_quality)}</strong></div><details><summary>Instructions, soldes, programmes, source et attributions</summary><pre>{JSON.stringify(r2Evidence, null, 2)}</pre></details></> : <div className="empty">Choisissez une signature de la cohorte ou d’une séquence.</div>}</section></div>
      <section className="panel"><span className="eyebrow">RATTACHEMENT FOMO · REVUE HUMAINE</span><h2>Déposer une preuve de profil et adresse publique</h2><p className="muted">Un lien de parrainage, y compris /r/nobrainflip, n’est pas une preuve. Toute saisie reste non attribuée jusqu’à revue séparée. Aucune clé privée ni cookie.</p><form className="two-col" onSubmit={submitProof}><div><label className="field-label">Profil Fomo URL ou identifiant<input value={proof.profile} onChange={e => setProof({ ...proof, profile: e.target.value })} required /></label><label className="field-label">Adresse publique Solana<input value={proof.address} onChange={e => setProof({ ...proof, address: e.target.value })} required /></label><label className="field-label">Type de preuve<select value={proof.proof_type} onChange={e => setProof({ ...proof, proof_type: e.target.value })}><option value="public_profile_explicit_address">Profil public et adresse explicite</option><option value="public_transaction_explicit_link">Transaction liée explicitement au profil</option><option value="authenticated_profile_and_deposit_screen">Écran connecté profil et dépôt</option><option value="authorized_export">Export autorisé</option><option value="other">Autre, non vérifiable automatiquement</option></select></label></div><div><label className="field-label">Référence locale ou URL de preuve<input value={proof.proof_reference} onChange={e => setProof({ ...proof, proof_reference: e.target.value })} placeholder="evidence/capture.png" required /></label><label className="field-label">Date de vérification UTC<input type="datetime-local" value={proof.verified_at.slice(0, 16)} onChange={e => setProof({ ...proof, verified_at: new Date(e.target.value + 'Z').toISOString() })} required /></label><label className="field-label">Auteur de la vérification<input value={proof.verified_by} onChange={e => setProof({ ...proof, verified_by: e.target.value })} required /></label><label className="field-label">Commentaire<input value={proof.comment} onChange={e => setProof({ ...proof, comment: e.target.value })} /></label><button className="button-primary" type="submit">Importer en attente de revue</button></div></form><p className="form-message">{r2Message}</p><div className="quality-row"><span>Preuves reçues / vérifiées</span><strong>{r2Proofs.length} / {r2Proofs.filter(p => p.status === 'verified').length}</strong></div><button className="button-secondary" onClick={() => download('r2-preuves-fomo.json', r2Proofs)}>Exporter les preuves</button></section></>}

      {tab === 'R3 réel' && <R3Panel />}
      {tab === 'Configuration' && <div className="two-col"><section className="panel"><span className="eyebrow">REGISTRES</span><h2>Watchlist et wallets</h2><p className="muted">Chaque token est identifié par son mint Solana. Un profil Fomo exige une preuve datée pour être relié à une adresse publique.</p><div className="quality-row"><span>Tokens actifs / archivés</span><strong>{tokens.length}</strong></div><div className="quality-row"><span>Wallets publics</span><strong>{wallets.length}</strong></div><div className="button-row"><button className="button-secondary" onClick={() => download('tokens.json', tokens)}>Exporter tokens</button><button className="button-secondary" onClick={() => download('wallets.json', wallets)}>Exporter wallets</button></div><div className="note">Les données de démo ne peuplent pas ces registres réels.</div></section>
      <section className="panel"><span className="eyebrow">IMPORT LOCAL</span><h2>Ajouter des données vérifiées</h2><div className="segmented"><button className={importKind === 'watchlist' ? 'active' : ''} onClick={() => setImportKind('watchlist')}>Watchlist</button><button className={importKind === 'wallets' ? 'active' : ''} onClick={() => { setImportKind('wallets'); setDraft('[\n  {\n    "address": "",\n    "category": "unknown"\n  }\n]') }}>Wallets</button></div><label className="field-label" htmlFor="json-draft">JSON local</label><textarea id="json-draft" value={draft} onChange={e => setDraft(e.target.value)} spellCheck={false}/><button className="button-primary" onClick={submitImport}>Importer</button>{message && <p className="form-message">{message}</p>}</section></div>}
    </main><footer><span>ROTATION ENGINE · RECHERCHE LOCALE</span><span>Ordres réels désactivés · Provenance et versions conservées</span></footer>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
