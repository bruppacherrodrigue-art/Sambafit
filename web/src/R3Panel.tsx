import { useEffect, useMemo, useState } from 'react'

type UniverseRow = { symbol: string; mint: string; network: string; category: string; role: string; status: string; reason: string; known_at: string }
type WalletRow = { wallet: string; provenance: string; strict_swaps: number; attributed_between_memecoins_usd: string | null; attributed_reserve_base_by_mint: Record<string, number>; gross_buy_usd: string | null; gross_sell_usd: string | null; passes_amount_screen: boolean; qualified_large_reallocator: boolean; holding_duration: string | null; opening_position_unknown: boolean; sample_signatures: string[] }
type RotationRow = { source: string; destination: string | null; source_op: string; destination_op: string | null; economic_at: string; available_at: string; amount_usd: string | null; reserve_quantity_base: number; reserve_mint: string; evidence: string; wallet: string }
type DecisionRow = { pair: string; at: string; state: string; quality: string; score: number; components: Record<string, number>; metrics: Record<string, string | null>; reasons: string[]; execution_quality: string; version: string }
type Bar = { close_at: string; available_at: string; price_usd: string; volume_usd: string | null; liquidity_usd: string | null; interval_seconds: number; source: string }
type Cohort = { cohort_known_at: string; sample_window: { start: string; end: string }; strict_swap_count: number; amount_screen_wallets: number; qualified_wallets: number; threshold_usd: string; wallets: WalletRow[]; sequences: { allocations: Array<{ source_signature: string; destination_signature: string }> } }
type Replay = { verified_operations: number; closed_market_bars: number; target_rotations: number; rotations: RotationRow[]; pairs_evaluated: string[]; decisions: DecisionRow[]; comparators: Record<string, { net_return: string | null; status?: string }> | null; execution_evidence: string; price_study_status: string }
type Prospective = { stages: Record<string, number>; stop_reason: string; missing_transitions: string[]; coverage_gaps: unknown[]; rotations: RotationRow[]; decisions: DecisionRow[]; execution_status: string }
type Budget = { limits: { max_calls: number; max_active_seconds: number }; calls_used: number; active_seconds: number; errors: unknown[] }
type Proof = { operation: Record<string, unknown>; raw: Record<string, unknown>; allocations: unknown[]; decisions: unknown[]; provenance: string; limitations: string[]; mode: string }

async function request<T>(path: string): Promise<T> {
  const response = await fetch(path)
  if (!response.ok) throw new Error(`${response.status} ${path}`)
  return response.json() as Promise<T>
}
const short = (value: string) => `${value.slice(0, 9)}…${value.slice(-6)}`
const when = (value?: string | null) => value ? `${new Date(value).toLocaleString('fr-CH', { timeZone: 'UTC' })} UTC` : 'indisponible'
const money = (value?: string | null) => value == null ? 'non comparable' : `${Number(value).toLocaleString('fr-CH', { maximumFractionDigits: 2 })} USD estimés`
const signature = (operationId: string) => operationId.split(':')[1] || operationId

function PairPrices({ source, destination, eventAt }: { source: string; destination: string; eventAt: string }) {
  const [sourceBars, setSourceBars] = useState<Bar[]>([])
  const [destinationBars, setDestinationBars] = useState<Bar[]>([])
  useEffect(() => {
    let active = true
    Promise.all([request<Bar[]>(`/api/r3/market/${source}`), request<Bar[]>(`/api/r3/market/${destination}`)])
      .then(([a, b]) => { if (active) { setSourceBars(a); setDestinationBars(b) } })
      .catch(() => { if (active) { setSourceBars([]); setDestinationBars([]) } })
    return () => { active = false }
  }, [source, destination])
  const aligned = useMemo(() => {
    const b = new Map(destinationBars.map(row => [row.close_at, row]))
    const rows = sourceBars.flatMap(a => {
      const match = b.get(a.close_at)
      if (!match || a.interval_seconds !== match.interval_seconds) return []
      const ratio = Number(match.price_usd) / Number(a.price_usd)
      return Number.isFinite(ratio) ? [{ at: a.close_at, a, b: match, ratio }] : []
    })
    const nearest = rows.reduce((best, row, index) =>
      Math.abs(new Date(row.at).getTime() - new Date(eventAt).getTime())
      < Math.abs(new Date(rows[best]?.at || row.at).getTime() - new Date(eventAt).getTime())
        ? index : best, 0)
    return rows.slice(Math.max(0, nearest - 10), nearest + 11)
  }, [sourceBars, destinationBars, eventAt])
  return <div><h3>Prix A, B et ratio B/A</h3><p className="muted">Clôtures de même intervalle uniquement ; réception du backfill distincte du temps économique. Événement : {when(eventAt)}. La profondeur historique est inconnue.</p>
    {aligned.length ? <div className="table-wrap"><table><thead><tr><th>Clôture UTC</th><th>A / USD</th><th>B / USD</th><th>B/A</th><th>Disponibles au bot</th></tr></thead><tbody>{aligned.map(row => <tr key={row.at}><td>{when(row.at)} {Math.abs(new Date(row.at).getTime() - new Date(eventAt).getTime()) <= row.a.interval_seconds * 1000 ? '← événement' : ''}</td><td>{row.a.price_usd}</td><td>{row.b.price_usd}</td><td>{row.ratio.toPrecision(5)}</td><td>{when(row.a.available_at)} / {when(row.b.available_at)}</td></tr>)}</tbody></table></div> : <div className="empty">Aucune observation A/B alignée dans les relevés archivés.</div>}
  </div>
}

export default function R3Panel() {
  const [universe, setUniverse] = useState<UniverseRow[]>([])
  const [cohort, setCohort] = useState<Cohort | null>(null)
  const [replay, setReplay] = useState<Replay | null>(null)
  const [prospective, setProspective] = useState<Prospective | null>(null)
  const [budget, setBudget] = useState<Budget | null>(null)
  const [proof, setProof] = useState<Proof | null>(null)
  const [selectedRotation, setSelectedRotation] = useState<RotationRow | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    Promise.all([
      request<{ records: UniverseRow[] }>('/api/r3/universe'), request<Cohort>('/api/r3/cohort'),
      request<Replay>('/api/r3/replay'), request<Prospective>('/api/r3/prospective'),
      request<Budget>('/api/r3/budget'),
    ]).then(([u, c, r, p, b]) => { setUniverse(u.records); setCohort(c); setReplay(r); setProspective(p); setBudget(b) })
      .catch(e => setError(String(e)))
  }, [])
  const name = (mint: string) => universe.find(row => row.mint === mint)?.symbol || short(mint)
  function openProof(sig: string) { request<Proof>(`/api/r3/operations/${sig}`).then(setProof).catch(e => setError(String(e))) }
  function save(name: string, value: unknown) {
    const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: 'application/json' }))
    const link = document.createElement('a'); link.href = url; link.download = name; link.click(); URL.revokeObjectURL(url)
  }
  return <>
    {error && <div className="error-box">Corpus R3 indisponible : {error}</div>}
    <section className="panel"><span className="eyebrow">REAL · R3 · RECHERCHE EXPLORATOIRE</span><h2>Univers memecoin Solana</h2><p className="muted">Classification candidate, sourcée et datée ; aucune allocation approuvée. SOL/wSOL et USDC sont des réserves, JUP/PUMP sont hors cible. PENGU reste en revue.</p>
      <div className="quality-row"><span>Appels R3 / plafond global</span><strong>{budget ? `${budget.calls_used} / ${budget.limits.max_calls}` : 'indisponible'}</strong></div>
      <div className="quality-row"><span>Collecte active / plafond</span><strong>{budget ? `${Math.round(budget.active_seconds)} / ${budget.limits.max_active_seconds} s` : 'indisponible'}</strong></div>
      <div className="table-wrap"><table><thead><tr><th>Coin · mint Solana</th><th>Rôle / catégorie</th><th>Statut</th><th>Motif / connu depuis</th></tr></thead><tbody>{universe.map(row => <tr key={row.mint}><td><strong>{row.symbol}</strong><br/><small className="mono">{row.mint}</small></td><td>{row.role} / {row.category}</td><td>{row.status}</td><td>{row.reason}<br/><small>{when(row.known_at)}</small></td></tr>)}</tbody></table></div><button className="button-secondary" onClick={() => save('r3-universe.json', universe)}>Exporter l’univers</button>
    </section>
    <div className="two-col"><section className="panel"><span className="eyebrow">COHORTE RÉTROSPECTIVE · NON ATTRIBUÉE À FOMO</span><h2>Candidats observés dans l’échantillon</h2><p className="muted">Fenêtre commune {when(cohort?.sample_window.start)} → {when(cohort?.sample_window.end)} ; gel de cohorte {when(cohort?.cohort_known_at)}. Seuil de présélection {cohort?.threshold_usd || '—'} USD ; positions antérieures inconnues.</p>
      <div className="quality-row"><span>Swaps stricts / wallets qualifiés</span><strong>{cohort?.strict_swap_count ?? '—'} / {cohort?.qualified_wallets ?? '—'}</strong></div>
      {cohort?.wallets.map(row => <div className="rank-row" key={row.wallet}><div><strong className="mono">{row.wallet}</strong><small>{row.provenance} · {row.strict_swaps} swaps · durée de détention {row.holding_duration || 'inconnue'}</small><small>Réallocations inférées {money(row.attributed_between_memecoins_usd)} ; réserve attribuée {JSON.stringify(row.attributed_reserve_base_by_mint)}</small><small>Achats {money(row.gross_buy_usd)} · ventes {money(row.gross_sell_usd)} · écran montant {row.passes_amount_screen ? 'oui' : 'non'} · gros wallet qualifié {row.qualified_large_reallocator ? 'oui' : 'non'}</small><button className="text-button" onClick={() => openProof(row.sample_signatures[0])}>Ouvrir une opération ↗</button></div></div>)}
      {!cohort?.wallets.length && <div className="empty">Aucun wallet vérifié dans cet échantillon.</div>}
      <button className="button-secondary" onClick={() => save('r3-cohort.json', cohort)}>Exporter la cohorte</button>
    </section><section className="panel"><span className="eyebrow">CHAÎNE PROSPECTIVE · PAPER LIVE</span><h2>Transitions et trous</h2><p className="muted">Suivi arrêté : {prospective?.stop_reason || 'indisponible'}. Un relevé sans rotation reste visible ; aucun ordre réel.</p>
      {Object.entries(prospective?.stages || {}).map(([stage, count]) => <div className="quality-row" key={stage}><span>{stage}</span><strong>{count}</strong></div>)}
      <p className="muted">Transitions manquantes : {prospective?.missing_transitions.join(', ') || 'aucune'}. Exécution : {prospective?.execution_status || 'indisponible'}.</p><details><summary>Trous de couverture ({prospective?.coverage_gaps.length ?? 0})</summary><pre>{JSON.stringify(prospective?.coverage_gaps, null, 2)}</pre></details>
      <button className="button-secondary" onClick={() => save('r3-prospective.json', prospective)}>Exporter le suivi</button>
    </section></div>
    <div className="two-col"><section className="panel"><span className="eyebrow">REPLAY RÉEL · SÉLECTION RÉTROSPECTIVE BIAISÉE</span><h2>Rotations A → B et décisions distinctes</h2><p className="muted">{replay?.target_rotations ?? '—'} attributions entre memecoins ; {replay?.pairs_evaluated.length ?? '—'} paires évaluées ; {replay?.closed_market_bars ?? '—'} bougies archivées. {replay?.price_study_status || ''}. Aucune inférence n’établit l’identité exacte des fonds.</p>
      {replay?.rotations.map((row, index) => <button className="timeline-item" key={`${row.source_op}-${row.destination_op}-${index}`} onClick={() => setSelectedRotation(row)}><span className="state-dot observing"/><span><strong>{name(row.source)} → {name(row.destination || '')}</strong><small>{when(row.economic_at)} · disponible {when(row.available_at)}</small></span><b>{money(row.amount_usd)}</b></button>)}
      {!replay?.rotations.length && <div className="empty">Zéro rotation dans ce corpus.</div>}
      {replay?.decisions.map((row, index) => <div className="signal-row" key={`${row.pair}-${row.at}-${index}`}><div><strong>{row.pair.split(':').map(name).join(' → ')} · {row.state}</strong><small>{when(row.at)} · qualité {row.quality} · score {row.score}/100 (hypothèse)</small><small>{row.reasons.join(', ') || 'aucun motif de blocage'}</small><details><summary>Features, contributions et version</summary><pre>{JSON.stringify({ metrics: row.metrics, components: row.components, execution_quality: row.execution_quality, version: row.version }, null, 2)}</pre></details></div></div>)}
      <h3>Comparateurs</h3>{Object.entries(replay?.comparators || {}).map(([key, row]) => <div className="quality-row" key={key}><span>{key}</span><strong>{row.net_return == null ? 'rendement non calculable' : row.net_return}</strong></div>)}
      <button className="button-secondary" onClick={() => save('r3-replay.json', replay)}>Exporter le replay</button>
    </section><section className="panel"><span className="eyebrow">PREUVE ET CHRONOLOGIE · REAL</span><h2>Opération et contexte A/B</h2>
      {selectedRotation ? <><div className="quality-row"><span>Paire</span><strong>{name(selectedRotation.source)} → {name(selectedRotation.destination || '')}</strong></div><div className="quality-row"><span>Réserve conservée</span><strong>{selectedRotation.reserve_quantity_base} unités de base · {short(selectedRotation.reserve_mint)}</strong></div><button className="text-button" onClick={() => openProof(signature(selectedRotation.source_op))}>Vente et preuve ↗</button><button className="text-button" onClick={() => selectedRotation.destination_op && openProof(signature(selectedRotation.destination_op))}>Achat et preuve ↗</button>{selectedRotation.destination && <PairPrices source={selectedRotation.source} destination={selectedRotation.destination} eventAt={selectedRotation.economic_at}/>}</> : <div className="empty">Choisissez une rotation ou une opération de la cohorte.</div>}
      {proof && <><div className="quality-row"><span>Mode / source</span><strong>{proof.mode} · {proof.provenance}</strong></div><div className="quality-row"><span>Signature</span><strong className="mono">{String(proof.operation.signature)}</strong></div><p className="muted">{proof.limitations.join(' ; ')}</p><details open><summary>Transaction brute, instructions, soldes, attributions et révisions</summary><pre>{JSON.stringify(proof, null, 2)}</pre></details></>}
    </section></div>
  </>
}
