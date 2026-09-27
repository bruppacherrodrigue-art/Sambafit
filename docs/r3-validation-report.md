# R3 — validation du moteur memecoin Solana, 27 septembre 2026

Base examinée : `origin/main` `486f55db6a0287ee6eca610a01c6afa61f184f00`. R2, ses données et ses rapports sont conservés. Tous les résultats ci-dessous portent l'étiquette **REAL exploratoire** ou **DEMO synthétique** ; aucun ordre réel n'a été signé ou diffusé.

## Constats C1–C4 et preuves

| Constat | Avant, reproduit | Après, preuve | Limite actuelle |
|---|---|---|---|
| C1 — rachat de A ignoré | Vente A 100, rachat A 100, achat B 100 produisait A→B 100 dans `r2_sequences.py` et `engine.py`. Les trois premières régressions ont échoué sur cette base. | `reserve_fifo.consume` commun aux deux chemins ; rachat A et achat hors univers consomment la réserve. Tests `test_fifo_buyback_consumes_sale_before_other_coin`, `test_engine_fifo_*`, unités de réserve et redémarrage passent. Migration 005 et SQLite `events_v3` distinguent plusieurs opérations d'une signature. | Les routes SOL natif/wSOL, loyers et conversions inter-réserves non prouvées restent partielles. |
| C2 — destination seule | `decide()` choisissait B et mélangeait A→B/C→B ; la fourchette de A et B/A ne décidaient rien. | `decide_pairs()` évalue séparément chaque paire admissible, avec fourchettes A/B, rendements, volatilité, volumes d'intervalles, ratio B/A aligné, flux plafonné, horloges et raisons. Régressions A seul, ratio seul, deux sources vers B et paires simultanées. API/UI exposent les décisions. | Données A/B reçues trop tard pour les cinq cas réels ; aucun score positif validé sur REAL. Persistance et groupes liés restent prudents/inconnus. |
| C3 — premiers trades, petits montants | R2 retenait trois achats et trois ventes par pool ; trois montants d'inférence d'environ 499, 298 et 49 USD. | Fenêtre commune, distribution et seuil de 500 USD fixés avant appels ; 24 références les plus grandes dédupliquées, 20 swaps stricts vérifiés indépendamment ; classement fondé sur montants réalloués et unités de réserve. Voir `r3-cohort-selection.md`, `preselection.json`, `verification.json`. | Aucun gros wallet directionnel qualifié ; quatre wallets observés, deux passent seulement l'écran de montant. Échantillon court, biais de sélection et routes partielles. |
| C4 — suivi avant décision | R2 gardait `requires_trade_reference`, `usd_value=None`, interrogeait au plus 20 signatures sans pagination complète et favorisait le premier wallet. | Pages de 20 avec curseur, file et trous persistés ; tour de priorité et transaction par wallet ; RPC null réessayable ; décodage de deux deltas propriétaire sans référence fournisseur obligatoire. Douze opérations incomplètes restent dans `enrichment_queue`, réexaminable hors réseau. `process_follow` emprunte le même `replay()` et les mêmes signaux que les archives. Test DEMO bout en bout jusqu'à `candidate`, API/UI et artefact REAL `prospective.json`. | Le suivi réel de ce lot n'a fourni aucune paire memecoin A/B vérifiée : il s'arrête avant une décision. 144 signatures restent en file, quatre trous sont déclarés ; la chaîne réelle de bout en bout n'est pas qualifiée. |

## Corpus nouveau et audit indépendant

La fenêtre de **présélection historique** est 2026-09-26 08:13:36–08:55:50 UTC sur dix pools candidats. Parmi 527 références dans cette fenêtre, 28 dépassent 500 USD ; 24 signatures ont été auditables dans la borne prévue. Le manifeste [`data/r3-20260927/manifest.json`](../data/r3-20260927/manifest.json) relie les 24 sélections et 16 transactions de suivi à leurs signatures, slots, heures, programmes, hashes et statuts. Il contient les 53 tentatives externes, sans secret.

Sur les 24 transactions sélectionnées, **20 swaps sont strictement attribués à quatre wallets on-chain non rattachés à Fomo**, quatre restent partiels. L'audit indépendant `verification.json` a comparé les montants des deux deltas SPL du propriétaire, le signataire et la référence fournisseur pour les 20 : zéro divergence relevée. « Strict » décrit cette opération économique bornée, et non toutes les instructions internes de la transaction. Aucun taux de décodage global n'est publié sur les routes inconnues.

Les 20 opérations produisent **cinq inférences memecoin→memecoin** via wSOL, entre cinq paires exactes. Elles sont rétrospectives et ne prouvent pas l'identité des fonds. Le portefeuille d'ouverture, la durée de détention et le patrimoine total des wallets sont inconnus. Le classement garde quatre wallets ; deux dépassent l'écran de 1 000 USD réalloués dans l'échantillon, **zéro n'est qualifié comme gros wallet directionnel durable**. Tous sont `onchain_unattributed`, zéro `fomo_verified`. Le formulaire existant garde toute nouvelle preuve Fomo en `pending_review` ; `/r/nobrainflip` reste une piste de parrainage, jamais une preuve d'adresse.

## Différence exacte avec les trois inférences R2

Le replay R3 reconstitue les mêmes 18 swaps R2 en unités de base de wSOL. `r2-comparison.json` garde les quatre lignes de différence sans toucher `data/r2-20260926/` :

| Paire R2 | Résultat R3 | Valeur descriptive R2 → R3 |
|---|---|---:|
| GOAT→BOME | même paire | 499,19 → 499,19 USD |
| MOODENG→FARTCOIN | même paire, attribution moindre | 298,16 → 248,81 USD |
| PNUT→MOODENG | supprimée | 49,38 → null |
| PNUT→FARTCOIN | nouvelle | null → 49,38 USD |

La conservation porte sur les unités wSOL ; le minimum des valorisations à la vente et à l'achat est une convention descriptive, pas une quote exécutable. Les trois inférences R2 ne sont donc ni toutes inchangées ni toutes invalides.

## Prix, décisions et comparateurs

Le replay R3 lit 597 bougies de minute closes déjà archivées en R2, avec leurs vraies **heures de réception du backfill**. Les cinq paires reçoivent chacune une révision `observing` : trois `missing_market`, deux `stale`. **Zéro `candidate`, zéro `confirmed` réel**. Le prix de swap isolé ne forme pas une série A/B connue à l'heure de décision. Un scénario synthétique distinct montre une décision `candidate` quand les deux jambes ont des prix alignés et une vente/achat conservés ; ce scénario ne constitue aucune preuve de profit.

Les quatre variantes panier conservé, marché seul, wallets seuls et combinaison sont exécutables sur les mêmes entrées admissibles, période et capital. Pour REAL R3, leurs `net_return` restent **null**, et non 0 %, faute de profondeur/quote historique et de période d'évaluation hors échantillon. Une étude de prix quantitative et un P&L exécutable restent non mesurables sur cette couverture. Le score sur 100 est une hypothèse, pas une probabilité.

## Observation prospective bornée

La cohorte a été figée le 27 septembre à 03:49:58 UTC. Deux cycles de suivi ont découvert et récupéré **16 nouvelles transactions** de quatre wallets ; 144 signatures restent en file et quatre trous de pagination sont explicites. Parmi les 16 : un swap complet après gel, trois routes partielles, huit opérations inconnues partielles, deux wraps, un programme non pris en charge et un échec. Le swap complet vend un mint **hors univers cible** contre wSOL : zéro réserve rapprochée pour une paire cible, zéro rotation cible, zéro paire évaluée en prospective. Les opérations hors univers demeurent visibles et peuvent consommer de la réserve dans l'attribution ; elles ne deviennent pas des extrémités de signal.

En parallèle, huit appels ont archivé **96 bougies de minute closes sur quatre mints candidats**, avec intervalles et réception, plus quatre snapshots de réserve de pool. Leur plage économique est 01:00–03:58 UTC le 27 septembre ; leur collecte ne prouve pas une observation continue de trois heures. Les volumes sont ceux de chaque bougie ; les snapshots de pool et volumes glissants ne sont pas ajoutés aux bougies. La profondeur historique et les quotes remplissables restent `null`.

Transition réelle : réception persistée **16** (dont **12 en file de réexamen du décodage**) → swaps complets **1** → réserve rapprochée avec coin cible **0** → rotations memecoin **0** → décision de paire **0** → ordre simulable **0**. Les motifs `incomplete_operations_await_enrichment` et `no_verified_memecoin_to_memecoin_rotation`, ainsi que le statut `blocked_no_historical_depth_or_quote`, sont persistés et consultables dans `/api/r3/prospective` et l'onglet **R3 réel**. `r3-refresh-follow` réévalue les réponses brutes localement après évolution du décodeur, sans nouvel appel. Le test DEMO vérifie le raccordement logiciel jusqu'à une décision sans masquer cet arrêt réel.

## Budget, contrôles et exploitation

Le budget R3 a été fixé **avant les appels** à 2 000 tentatives, 1 800 secondes actives et 0 USD payant, avec sous-plafonds persistants : audit cohorte 30/300 s, suivi 40/300 s, marché 20/180 s. Utilisation : **53 tentatives HTTP 200**, **491,03 secondes** actives ; 21 appels d'audit RPC, 24 appels de suivi (signatures et transactions), huit appels marché. Aucune dépense payante, aucun HTTP 429 dans ce lot. Les attentes de limitation et les timeouts sont bornés par le temps restant. Un éventuel HTTP 429 serait archivé avec son `Retry-After`, puis arrêterait le cycle sans relance automatique. Aucun service de collecte périodique n'a été laissé actif.

Contrôles locaux : `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run pytest -q` (**115 réussis**), `cd web && npm run build`. Les tests vérifient notamment consommation FIFO, identité d'opération, absence de données futures, pagination, équité, RPC null, budget, API REAL et chaîne DEMO. Un navigateur automatisable n'était pas installé ; l'interface a été compilée et l'API testée par `TestClient` et HTTP local. L'API locale répond `REAL, 16 transactions` et le proxy Vite sert 15 entrées du registre R3 avec HTTP 200.

Reproduction **sans nouvel appel externe** :

```bash
uv sync --frozen
uv run rotation r3-cohort
uv run rotation r3-replay
uv run rotation r3-refresh-follow
uv run rotation r3-process-follow
uv run rotation r3-manifest
uv run rotation r3-budget
uv run pytest -q
cd web && npm ci && npm run build
```

Les commandes `r3-audit`, `r3-follow-once` et `r3-market-follow` effectuent des appels externes et reprennent le budget R3 persistant ; elles ne sont pas nécessaires pour reproduire les preuves déjà archivées. Pour servir localement l'interface, voir le README. `ROTATION_KILL_SWITCH=1` bloque tout nouvel appel de collecte. Aucun ordre réel n'existe.

Services locaux laissés actifs pour revue, sans collecte : API Uvicorn `127.0.0.1:8011` (processus parent 1005846, enfant 1005854), Vite `127.0.0.1:5176` (parent 983383, enfant 983436). Les services R2 déjà présents sur d'autres ports n'ont pas été interrompus. Arrêter uniquement les parents R3 identifiés avec `kill 1005846 983383` après avoir revérifié leur ligne de commande ; les sessions interactives peuvent aussi recevoir `Ctrl-C`. La base PostgreSQL préexistante reste active. Coût des services locaux constaté : 0 USD facturé dans ce lot.

**Statut :** défauts C1–C4 corrigés dans le code et régressions vertes ; méthode de cohorte et chaîne DEMO démontrées ; replay réel exploratoire et suivi borné observés ; chaîne réelle complète, qualification de gros wallets, rattachement Fomo et avantage financier **non établis**. R3 ne doit pas être présenté comme une validation financière ou comme une observation prospective achevée.
