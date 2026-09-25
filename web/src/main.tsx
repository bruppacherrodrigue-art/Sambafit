import React, { useEffect, useMemo, useState } from 'react'
import { createRoot } from 'react-dom/client'
import './style.css'

type Dataset = 'DEMO' | 'REAL' | 'REPLAY'
type Tab = 'Vue générale' | 'Flux et signaux' | 'Marché' | 'Expériences' | 'Configuration'
type Overview = { dataset: Dataset; wallets: number; tokens: number; raw_events: number; operations: number; market_bars: number; signals: number; open_gaps: number }
type Signal = { pair: string; decision_at: string; state: string; quality: string; score: number; components: Record<string, number>; reasons: string[]; config_hash: string; dataset: string }
type Rotation = { source: string; destination: string | null; evidence: string; direction: string; amount_usd: string; wallet: string; source_op: string; destination_op: string | null; economic_at: string; available_at: string }
type Bar = { mint: string; close_at: string; available_at: string; price_usd: string; volume_usd: string; liquidity_usd: string | null; source: string; dataset: string }
type Wallet = { address: string; category: string; fomo_profile: string | null; proof: string | null; confidence: string | null }
type Token = { mint: string; symbol: string | null; decimals: number; active: boolean }
type Experiment = { id: string; dataset: string; status: string; config_hash: string; result: Record<string, unknown>; started_at: string }
type Coverage = { checkpoints: Array<Record<string, unknown>>; gaps: Array<Record<string, unknown>>; note?: string }
type Operation = { signature: string; wallet: string; kind: string; quality: string; economic_at: string; available_at: string; legs: Array<{ mint: string; delta_base: string; usd_price: string | null }> }

async function get<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${path}`)
  return response.json() as Promise<T>
}
const fmt = (value: number, digits = 0) => new Intl.NumberFormat('fr-CH', { maximumFractionDigits: digits }).format(value)
const time = (value?: string) => value ? new Date(value).toLocaleString('fr-CH', { dateStyle: 'short', timeStyle: 'short', timeZone: 'UTC' }) + ' UTC' : '—'
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
  const [operations, setOperations] = useState<Operation[]>([])
  const [wallets, setWallets] = useState<Wallet[]>([])
  const [tokens, setTokens] = useState<Token[]>([])
  const [experiments, setExperiments] = useState<Experiment[]>([])
  const [coverage, setCoverage] = useState<Coverage | null>(null)
  const [sourceBars, setSourceBars] = useState<Bar[]>([])
  const [destBars, setDestBars] = useState<Bar[]>([])
  const [selected, setSelected] = useState<Signal | null>(null)
  const [evidence, setEvidence] = useState<Record<string, unknown> | null>(null)
  const [error, setError] = useState('')
  const [draft, setDraft] = useState('[\n  {\n    "network": "solana",\n    "mint": "",\n    "symbol": "",\n    "decimals": 6,\n    "eligible_from": "2026-09-25T00:00:00Z"\n  }\n]')
  const [importKind, setImportKind] = useState<'watchlist' | 'wallets'>('watchlist')
  const [message, setMessage] = useState('')

  useEffect(() => {
    let mounted = true
    const q = `?dataset=${encodeURIComponent(dataset)}`
    const sourceQ = `?dataset=${dataset === 'REPLAY' ? 'REAL' : dataset}`
    Promise.all([get<Overview>('/api/overview' + q), get<Signal[]>('/api/signals' + q),
      get<Rotation[]>('/api/rotations' + sourceQ), get<Operation[]>('/api/operations' + sourceQ),
      get<Wallet[]>('/api/wallets'), get<Token[]>('/api/tokens'),
      get<Experiment[]>('/api/experiments' + sourceQ), get<Coverage>('/api/coverage' + sourceQ)])
      .then(([o, s, r, ops, w, t, ex, c]) => { if (mounted) { setOverview(o); setSignals(s); setRotations(r); setOperations(ops); setWallets(w); setTokens(t); setExperiments(ex); setCoverage(c); setSelected(s[0] || null); setError('') } })
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

  const ratioBars = useMemo(() => {
    const a = new Map(sourceBars.map(b => [b.close_at, Number(b.price_usd)]))
    return destBars.filter(b => a.has(b.close_at) && a.get(b.close_at)! > 0)
      .map(b => ({ ...b, price_usd: String(Number(b.price_usd) / a.get(b.close_at)!) }))
  }, [sourceBars, destBars])
  const ranking = useMemo(() => Object.entries(rotations.reduce<Record<string, { usd: number; count: number; direct: number }>>((acc, r) => {
    const item = acc[r.wallet] || { usd: 0, count: 0, direct: 0 }
    item.usd += Number(r.amount_usd); item.count += 1; item.direct += Number(r.evidence === 'direct'); acc[r.wallet] = item; return acc
  }, {})).sort((a, b) => b[1].usd - a[1].usd), [rotations])
  const tabs: Tab[] = ['Vue générale', 'Flux et signaux', 'Marché', 'Expériences', 'Configuration']

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
      <div className="top-actions"><span className="local-pill">● LOCAL / PRIVÉ</span><span className={`mode-pill ${dataset.toLowerCase()}`}>{dataset === 'DEMO' ? 'DEMO · SYNTHÉTIQUE' : dataset === 'REPLAY' ? 'REPLAY · HISTORIQUE' : 'RECHERCHE · RÉEL'}</span></div></header>
    <main className="main"><section className="intro"><div><div className="eyebrow">SOLANA · ANALYSE DES FLUX</div><h1>Observer les rotations,<br/><em>vérifier les preuves.</em></h1><p>Décisions déterministes à partir des flux attribués, du marché disponible et de leur qualité. Aucun ordre réel.</p></div><div className="mode-switch"><label>JEU DE DONNÉES</label><button className={dataset === 'DEMO' ? 'active' : ''} onClick={() => setDataset('DEMO')}>Démo</button><button className={dataset === 'REAL' ? 'active' : ''} onClick={() => setDataset('REAL')}>Réel</button><button className={dataset === 'REPLAY' ? 'active' : ''} onClick={() => setDataset('REPLAY')}>Replay</button></div></section>
      {error && <div className="error-box">{error}<br/><code>rotation doctor</code> puis démarrez l’API locale.</div>}
      <div className="disclosure"><strong>{dataset === 'DEMO' ? 'Scénario synthétique' : 'Données réelles non qualifiées'}</strong><span>{dataset === 'DEMO' ? 'Les wallets, mints, prix et résultats de cette vue sont fictifs. Ils démontrent le logiciel, pas une stratégie.' : 'Aucun signal ne vaut preuve d’avantage financier. La couverture des comptes et la liquidité historique restent à qualifier.'}</span></div>
      <nav className="tabs">{tabs.map(t => <button key={t} className={tab === t ? 'active' : ''} onClick={() => setTab(t)}>{t}</button>)}</nav>

      {tab === 'Vue générale' && <><div className="metric-grid">
        <article className="metric"><span>ÉVÉNEMENTS BRUTS</span><strong>{overview ? fmt(overview.raw_events) : '—'}</strong><small>{dataset === 'DEMO' ? 'fixture synthétique' : 'source RPC'}</small></article>
        <article className="metric"><span>OPÉRATIONS</span><strong>{overview ? fmt(overview.operations) : '—'}</strong><small>finalisées ou qualité explicitée</small></article>
        <article className="metric"><span>SIGNAUX</span><strong>{overview ? fmt(overview.signals) : '—'}</strong><small>révisions persistées</small></article>
        <article className="metric"><span>TROUS OUVERTS</span><strong>{overview ? fmt(overview.open_gaps) : '—'}</strong><small>couverture réelle séparée</small></article>
      </div><div className="two-col"><section className="panel"><div className="section-head"><div><span className="eyebrow">QUALITÉ</span><h2>État de la collecte</h2></div><span className="subtle">{dataset}</span></div>
        <div className="quality-row"><span>Wallets enregistrés</span><strong>{overview?.wallets ?? '—'}</strong></div><div className="quality-row"><span>Tokens surveillés</span><strong>{overview?.tokens ?? '—'}</strong></div><div className="quality-row"><span>Bougies disponibles</span><strong>{overview?.market_bars ?? '—'}</strong></div><div className="quality-row"><span>Dernière opération disponible</span><strong>{time(operations.at(-1)?.available_at)}</strong></div>
        <div className="note">{coverage?.note || (coverage?.gaps.length ? `${coverage.gaps.length} trou(s) de collecte demandent vérification.` : 'Aucun trou enregistré. Cela ne prouve pas une couverture complète des comptes de tokens fermés.')}</div></section>
        <section className="panel"><div className="section-head"><div><span className="eyebrow">DÉCISIONS</span><h2>Chronologie récente</h2></div><button className="text-button" onClick={() => setTab('Flux et signaux')}>Voir les preuves →</button></div>{signals.length ? signals.slice(-5).reverse().map((s, i) => <button key={`${s.pair}-${i}`} className="timeline-item" onClick={() => { setSelected(s); setTab('Flux et signaux') }}><span className={`state-dot ${s.state}`}></span><span><strong>{s.pair}</strong><small>{time(s.decision_at)} · {s.quality}</small></span><b>{stateName[s.state] || s.state}</b></button>) : <div className="empty">Aucun signal enregistré dans ce jeu de données.</div>}</section></div></>}

      {tab === 'Flux et signaux' && <><div className="two-col flow-layout"><section className="panel"><div className="section-head"><div><span className="eyebrow">ATTRIBUTION</span><h2>Flux entre coins</h2></div><button className="text-button" onClick={() => download(`rotations-${dataset}.json`, rotations)}>Exporter JSON ↗</button></div>
        {rotations.length ? <div className="table-wrap"><table><thead><tr><th>Origine → destination</th><th>Preuve</th><th>Montant attribué</th><th>Wallet</th></tr></thead><tbody>{rotations.map((r, i) => <tr key={i}><td><strong>{r.source} → {r.destination || 'inconnue'}</strong><small>{r.direction}</small></td><td><span className={`evidence-pill ${r.evidence}`}>{r.evidence}</span></td><td>{fmt(Number(r.amount_usd), 2)} $</td><td>{r.wallet}</td></tr>)}</tbody></table></div> : <div className="empty">Aucun flux attribuable. Un transfert ou un décodage partiel ne devient pas une rotation.</div>}</section>
        <section className="panel"><div className="section-head"><div><span className="eyebrow">COHORTE</span><h2>Wallets par capital réalloué</h2></div></div>{ranking.length ? ranking.map(([wallet, item], i) => <div className="rank-row" key={wallet}><span className="rank-num">{String(i + 1).padStart(2, '0')}</span><div><strong>{wallet}</strong><small>{wallets.find(w => w.address === wallet)?.category || 'inconnu'} · {item.count} attribution(s) · {item.direct} directe(s)</small></div><b>{fmt(item.usd)} $</b></div>) : <div className="empty">Aucun wallet classable. Le P&amp;L Fomo seul ne qualifie pas un gros trader.</div>}</section></div>
        <div className="two-col"><section className="panel"><div className="section-head"><div><span className="eyebrow">MACHINE D’ÉTATS</span><h2>Révisions des signaux</h2></div><button className="text-button" onClick={() => download(`signaux-${dataset}.csv`, signals, true)}>Exporter CSV ↗</button></div>{signals.length ? signals.map((s, i) => <button key={i} className={`signal-row ${selected === s ? 'selected' : ''}`} onClick={() => setSelected(s)}><span className={`state-dot ${s.state}`}></span><div><strong>{s.pair}</strong><small>{time(s.decision_at)} · {s.quality}</small></div><b>{stateName[s.state] || s.state}</b><span className="score">{s.score}/100</span></button>) : <div className="empty">Aucune révision.</div>}</section>
        <section className="panel evidence-panel"><div className="section-head"><div><span className="eyebrow">POURQUOI / PREUVES</span><h2>{selected?.pair || 'Sélectionner un signal'}</h2></div>{selected && <span className={`state-label ${selected.state}`}>{stateName[selected.state] || selected.state}</span>}</div>
        {selected ? <><p className="muted">Score hypothétique {selected.score}/100. Ce score n’est pas une probabilité de réussite.</p><div className="component-list">{Object.entries(selected.components).map(([name, score]) => <div key={name}><span>{name.replaceAll('_', ' ')}</span><b>{score}</b></div>)}</div><h3>Raisons</h3><ul>{selected.reasons.map((reason, i) => <li key={i}>{reason}</li>)}</ul><h3>Traçabilité</h3><p className="mono small">Config {selected.config_hash.slice(0, 18)}…<br/>Décision {time(selected.decision_at)}<br/>Qualité {selected.quality}<br/>Source {evidence ? String((evidence.raw as Record<string, unknown>).source) : 'indisponible'}</p>{evidence && <details><summary>Réponse brute et opération normalisée</summary><pre>{JSON.stringify(evidence, null, 2)}</pre></details>}</> : <div className="empty">Cliquez sur une révision pour inspecter ses raisons.</div>}</section></div></>}

      {tab === 'Marché' && <><div className="market-title"><div><span className="eyebrow">CONTEXTE DISPONIBLE À LA DÉCISION</span><h2>{pair || 'Aucune paire sélectionnée'}</h2></div><span className="subtle">Prix de clôture · aucun prix futur dans la décision</span></div><div className="two-col"><section className="panel"><LineChart bars={destBars} title={`${destination || 'B'} / USD`} events={signals.filter(s => s.pair === pair)} /></section><section className="panel"><LineChart bars={ratioBars} title={`${destination || 'B'} / ${source || 'A'}`} events={signals.filter(s => s.pair === pair)} /></section></div><div className="note wide">Les marqueurs indiquent l’heure de disponibilité du signal. Les graphiques utilisent les bougies closes. Une quote historique exécutable n’est pas fournie par ces seules bougies.</div></>}

      {tab === 'Expériences' && <><div className="section-head standalone"><div><span className="eyebrow">REPLAY / PAPER</span><h2>Expériences enregistrées</h2></div></div>{experiments.length ? <div className="experiment-grid">{experiments.map(e => <article className="panel experiment" key={e.id}><div className="experiment-top"><span className="evidence-pill">{e.result.initial_cash ? 'PAPER' : 'REPLAY'}</span><span className="subtle">{time(e.started_at)}</span></div><h3>{e.result.initial_cash ? 'Portefeuille simulé' : 'Étude de signaux'}</h3><p>{e.result.synthetic ? 'Données synthétiques DEMO' : 'Données réelles non qualifiées'}</p><div className="quality-row"><span>Opérations simulées</span><strong>{String(e.result.filled_orders ?? e.result.rotations ?? '—')}</strong></div><div className="quality-row"><span>Cash final</span><strong>{String(e.result.ending_cash ?? '—')}</strong></div><div className="quality-row"><span>Avantage financier</span><strong>Non évalué</strong></div><details><summary>Rapport JSON et hypothèses</summary><pre>{JSON.stringify(e.result, null, 2)}</pre></details><small className="mono">{e.id}</small></article>)}</div> : <div className="panel empty">Aucune expérience. Exécutez <code>rotation replay</code> puis <code>rotation paper</code>.</div>}</>}

      {tab === 'Configuration' && <div className="two-col"><section className="panel"><span className="eyebrow">REGISTRES</span><h2>Watchlist et wallets</h2><p className="muted">Chaque token est identifié par son mint Solana. Un profil Fomo exige une preuve datée pour être relié à une adresse publique.</p><div className="quality-row"><span>Tokens actifs / archivés</span><strong>{tokens.length}</strong></div><div className="quality-row"><span>Wallets publics</span><strong>{wallets.length}</strong></div><div className="button-row"><button className="button-secondary" onClick={() => download('tokens.json', tokens)}>Exporter tokens</button><button className="button-secondary" onClick={() => download('wallets.json', wallets)}>Exporter wallets</button></div><div className="note">Les données de démo ne peuplent pas ces registres réels.</div></section>
      <section className="panel"><span className="eyebrow">IMPORT LOCAL</span><h2>Ajouter des données vérifiées</h2><div className="segmented"><button className={importKind === 'watchlist' ? 'active' : ''} onClick={() => setImportKind('watchlist')}>Watchlist</button><button className={importKind === 'wallets' ? 'active' : ''} onClick={() => { setImportKind('wallets'); setDraft('[\n  {\n    "address": "",\n    "category": "unknown"\n  }\n]') }}>Wallets</button></div><label className="field-label" htmlFor="json-draft">JSON local</label><textarea id="json-draft" value={draft} onChange={e => setDraft(e.target.value)} spellCheck={false}/><button className="button-primary" onClick={submitImport}>Importer</button>{message && <p className="form-message">{message}</p>}</section></div>}
    </main><footer><span>ROTATION ENGINE · RECHERCHE LOCALE</span><span>Ordres réels désactivés · Provenance et versions conservées</span></footer>
  </div>
}

createRoot(document.getElementById('root')!).render(<React.StrictMode><App /></React.StrictMode>)
