# R3.1 — validation des horloges et de la stratégie, 27 septembre 2026

Base vérifiée avant édition : branche `feat/r3-memecoin-rotation-engine`, tête locale et distante `2f0aced054583c7618bba7a1ca79d65357c1a84f`, PR [#1](https://github.com/bruppacherrodrigue-art/Sambafit/pull/1) en brouillon, `main` à `486f55db6a0287ee6eca610a01c6afa61f184f00`, arbre propre. Aucun fichier `AGENTS.md` du dépôt. Les archives `data/r2-20260926/` et `data/r3-20260927/` n'ont pas été modifiées. Les sorties R3.1 sont [séparées](../data/r3-1-20260927/replay.json). Aucun appel marché/RPC nouveau, collecte périodique, ordre réel, abonnement ou déploiement.

## Défauts T1–T3 : reproduction puis correction

| Défaut | Avant sur R3 | Après R3.1 | Régression |
|---|---|---|---|
| T1 — vieux flux reçu maintenant | La fixture A→B de 1 500 USD, vieille de 7 jours économiquement mais reçue à T+3 min, était `candidate` avec 604 980 s de retard. Le filtre regardait `available_at`. | `assess_flow_clock` refuse l'âge économique > 6 h et le retard de disponibilité > 15 min, avec deux métriques et motifs. Bornes inclusives, horloges futures/incohérentes refusées. `decide`, agrégation et comparateur wallet appliquent cette règle. Le candidat synthétique ancien est `expired`, jamais promu. | `test_t1_*`, `test_wallet_baseline_does_not_promote_week_old_flow_received_now` |
| T2 — preuve disparue sans révision | Vente A→R T, achat R→B T+2 disponible T+3 : `candidate`. Rachat R→A économique T+1 reçu T+4 : attributions finales vides mais candidate non annulée. | Chaque lot recalcule les paires. À T+4, révision `invalidated/proof_removed` ; la candidate de T+3 reste inchangée. Une réduction de montant révise le score/preuve ; une correction de classification peut retirer la paire. Une archive déjà expirée reçoit `observing/proof_removed`, pas une fausse invalidation de marché. Une horloge d'expiration ferme un épisode sans nouveau swap ; référence d'entrée paper réinitialisée. | `test_t2_*`, `test_retraction_revises_signal_without_duplicate_trade`, `test_r31_paper_cycle.py` |
| T3 — enrichissement antidaté | Le test ciblé a constaté qu'un redécodage remplaçait les champs de la transaction sans `decoded_at`/`effective_available_at` et réutilisait implicitement l'heure de réception brute. | Révisions de décodage conservant l'ancien état et horodatant la nouvelle preuve par une horloge injectable. Une vérification d'archive sans horloge historique fiable crée une preuve **maintenant**, pas à la réception initiale. `process_follow` utilise l'heure effective ; un prix reçu plus tard crée une version de valorisation du même ID à sa réception. Une correction d'identité sourcée et datée remplace l'ancien acteur à la disponibilité maximale de sa preuve. Les lignes REAL historiques sans date de décodage sont exclues de la décision prospective jusqu'à revérification. | `test_t3_*`, `test_wallet_identity_correction_replaces_old_actor_only_when_known`, `test_r3_pipeline.py` |

Les tests T1/T2/T3 ont été exécutés **rouges avant correction** : T1 retournait `candidate`, T2 ne produisait qu'une candidate, T3 levait `KeyError('effective_available_at')`. Les tests de décodage et de prix tardifs montrent que les données futures ne modifient pas une ancienne décision. Les décisions répétées et la reprise déterministe n'ajoutent pas d'effet paper. Une candidate/confirmée ne se maintient pas indéfiniment sans preuve fraîche.

## Référence de stratégie et limites explicites

La [spécification versionnée](strategy-spec.md) et [`config/strategy-r3-1.json`](../config/strategy-r3-1.json) sont la source des règles communes replay/suivi. Hash de la configuration exécutée : `248096b910c88acc8fd4d93d9fafdbbd5611a851d7efa2eab1da0640912cc846`. Le score de **recherche** et l'admission **stricte** sont séparés. L'admission exige deux memecoins Solana par mint, preuves datées de durabilité/liquidité/couverture/revue communautaire, range oscillant qualifié, réallocation d'au moins deux groupes de gros wallets directionnels connus à l'heure de décision. Zéro des actifs R3 n'est admis à une simulation de stratégie ; zéro wallet ne satisfait le critère de gros réallocateur durable et zéro adresse Fomo n'est vérifiée. Le lien de parrainage n'est pas une preuve. Le paper exige quotes, profondeur et coûts complets ; les archives ne les contiennent pas.

Une série synthétique oscillante valide le calcul causal de range ; séries monotones, plateau et rupture sont rejetés. Une démonstration DEMO du `PaperCycle` montre attente sans B admissible, vente A remplie/achat B échoué avec cash conservé, déduplication, sortie et réentrée à nouveau prix de référence. Elle **ne mesure aucun profit**. Le rapport gain/risque est une estimation conditionnelle à des quotes et coûts connus, pas une probabilité. Aucun chemin ne signe/diffuse un ordre réel. Les nouveaux champs JSON de suivi sont facultatifs et rétrocompatibles ; aucune migration PostgreSQL n'a été nécessaire pour cette livraison.

## Replay réel, avant/après

Les 18 swaps R2 conservent exactement le résultat d'attribution R3 : trois allocations actuelles, avec GOAT→BOME inchangée, MOODENG→FARTCOIN réduite, PNUT→MOODENG retirée et PNUT→FARTCOIN apparue. Les unités de réserve et les lignes de [comparaison R3.1](../data/r3-1-20260927/r2-comparison.json) sont identiques à R3. Aucune réécriture de `data/r2-*` ou `data/r3-*`.

Sur les 20 swaps stricts R3 audités, les **cinq rotations inférées finales** restent les mêmes, entre **quatre paires finales distinctes** : WIF→FARTCOIN, PNUT→FARTCOIN (deux attributions), FARTCOIN→WIF et BOME→WIF. Une cinquième paire **transitoire** PNUT→WIF apparaît lors d'une réception dans le désordre puis perd sa preuve. Ces noms sont seulement des libellés ; tous les calculs utilisent les mints exacts du registre. La cohorte rétrospective de quatre wallets reste biaisée par sélection et n'est pas un test indépendant.

| Mesure | R3 archivé | R3.1 hors réseau |
|---|---:|---:|
| Rotations inférées finales | 5 | 5 |
| Paires jamais évaluées, transitoires comprises | 5 | 5 |
| Révisions de décision | 5 `observing` : 3 marché absent, 2 périmé | 9 : 8 `expired/stale_flow`, 1 `observing/proof_removed` |
| Candidate / confirmée réelles | 0 / 0 | 0 / 0 |
| Admission stricte | non évaluée | 0 ; 9 révisions `blocked` |
| Valorisation d'exécution/P&L des 4 comparateurs | `null` | `null` |

Les transactions des cinq rotations économiques datent du 26 septembre 08:29–08:53 UTC et leurs preuves utilisées ont été reçues le 27 septembre vers 03:45–03:48 UTC. Le retard d'environ **18,9–19,3 h** dépasse le plafond technique de 15 min et l'âge de 6 h. Le replay R3.1 les archive sans inventer une décision bot qui aurait existé la veille. La réception brute est une **borne inférieure** de disponibilité pour les audits historiques dont l'heure exacte de décodage n'a pas été conservée ; cette incertitude est exposée sous `availability_clock_quality`. Le marché R2 fournit 597 bougies de minute archivées, mais il n'établit ni un range strict de trois jours connu à l'époque ni une profondeur/quote historique. Les comparateurs panier, marché seul, wallets seuls et combiné restent exécutables logiciellement sur mêmes entrées ; leur rendement réel demeure `null`, jamais 0 %.

Le suivi archivé contient toujours 16 transactions récupérées, dont 12 opérations incomplètes à enrichir, 144 signatures en file et 96 bougies sur quatre mints. La sortie R3.1 porte `REAL / REPLAY` : elle reconstruit hors ligne des entrées collectées prospectivement en R3 et ne représente pas un service `PAPER LIVE` actif aujourd'hui. Une ligne est un swap complet après gel de cohorte mais **hors cible** ; son heure historique de décodage n'est pas enregistrée. R3.1 la signale comme `legacy_decode_availability_unknown` et ne la transforme pas en décision prospective rétrodatée : **1 swap brut complet, 0 swap à horloge de preuve qualifiée, 0 rotation cible, 0 paire évaluée, 0 ordre paper**. Il n'y a eu aucun nouveau cycle de suivi et ces 96 bougies ne constituent pas plusieurs jours d'observation. Un prix reçu après une opération peut désormais générer une révision de valorisation à sa vraie disponibilité, démontrée par fixture DEMO ; le corpus REAL ne fournit pas de nouveau prix utilisable pour cette ligne.

## Contrôles, reproduction et exploitation

Reproduction **hors réseau de données** depuis la racine :

```bash
uv sync --frozen
uv run rotation r3-1-replay --root data/r3-20260927 --r2-root data/r2-20260926 --out data/r3-1-20260927
uv run rotation r3-1-process-follow --root data/r3-20260927 --out data/r3-1-20260927
uv run ruff format --check src tests
uv run ruff check src tests
uv run pytest -q
cd web && npm run build
```

API locale : `/api/r3-1/replay`, `/api/r3-1/prospective`, `/api/r3-1/strategy`. Ces endpoints REAL refusent un artefact DEMO. L'onglet **R3 réel** affiche les trois horloges disponibles, les révisions, les raisons d'expiration/annulation et le blocage d'admission. Les sorties R3.1 sont des JSON déterministes et un SQLite local reproductible ; aucun service réseau n'est nécessaire pour les reconstruire. Le test API, un GET HTTP local `200 REAL/9 révisions` et le build vérifient cette surface. La vérification visuelle Playwright a été tentée, mais Chromium/Chrome n'est pas installé (`Chromium distribution 'chrome' is not found`) ; aucune capture ni validation visuelle automatisée n'est revendiquée. Le serveur API temporaire `127.0.0.1:8012` et Vite `127.0.0.1:5177` ont été arrêtés par leurs sessions après ce contrôle. Les services locaux préexistants n'ont pas été arrêtés ni redéployés pour ce lot ; leurs PID doivent être revérifiés avant arrêt ciblé. Aucun nouveau service ni worker n'est laissé actif. Coût payant constaté : **0 USD**. Appels de données externes nouveaux : **0** ; seuls les échanges GitHub/CI de livraison sont autorisés.

**Statut :** corrections temporelles et couche d'admission logicielle démontrées ; replay REAL exploratoire reproductible ; suivi prospectif avec horloge héritée inconnue bloqué jusqu'à revérification ; rendement, avantage prédictif, communauté durable, gros wallets qualifiés, lien Fomo et P&L exécutable **non mesurables sur ces archives**.
