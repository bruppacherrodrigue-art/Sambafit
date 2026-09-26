# R2 — nouveaux résultats du 26 septembre 2026

Ce rapport couvre **seulement les apports R2**. Le pilote DLMM précédent reste décrit dans `real-pilot-report.md`. L'univers est une proposition de recherche et la cohorte est sélectionnée **après** le prélèvement : ses résultats antérieurs sont exploratoires, avec biais de sélection. Aucune attribution Fomo, performance financière ni aptitude à exécuter des ordres n'en découle.

## Livré et observé

| Élément R2 | Résultat réel / état |
|---|---|
| Univers | 11 `research_candidate` à mint Solana exact, pool identifié et mint SPL vérifié ; PUMP conservé comme exclu du périmètre. SOL/wSOL et USDC restent des réserves/transits. `config/r2-candidates.json` enregistre la date de connaissance, les seuils, les snapshots et les preuves source. |
| Découverte | Trades publics de 11 pools ; 66 signatures distinctes sélectionnées par règle fixe de 3 achats + 3 ventes/pool ; 36 adresses annoncées par le fournisseur, **sans promotion automatique en trader**. |
| Chaîne vérifiée | 66 transactions finalisées récupérées ; 18 swaps stricts, 30 routes partielles, 15 décodages partiels, 3 programmes non pris en charge. Dix swaps stricts recomptés séparément à partir des instructions, soldes SPL, signataires et frais. Aucun taux global de décodage ne serait honnête sans dénominateur des swaps économiques des 48 opérations incertaines. |
| Cohorte stricte | 3 wallets on-chain non attribués à Fomo, sur 07:05:48–09:07:30 UTC ; 13 des 18 swaps appartiennent à un wallet à automatisation/arbitrage probable. Cible indicative de 20–40 wallets non atteinte. Classement global par USD réalloué **dans cet échantillon** et classements par coin exportés ; couverture entre pools/programmes inégale. |
| Séquences | 3 réallocations **inférées via wSOL** (GOAT→BOME 499,19 USD ; MOODENG→FARTCOIN 298,16 USD ; PNUT→MOODENG 49,38 USD, valeur proxy fournisseur). Zéro A→B spéculatif direct, zéro convergence multi-wallet vérifiée. Une acquisition depuis réserve ne devient pas une rotation fictive. Ventes restantes et allocations FIFO persistées en SQLite ; l'identité des fonds, l'intention et les positions antérieures restent inconnues. |
| Suivi borné | 4 relevés prospectifs de pools reçus entre 09:33 et 09:42 UTC (BONK, WIF, PENGU, POPCAT), avec prix, réserve instantanée et volume **glissant** 24 h ; 75 transactions nouvelles de deux wallets suivis, plage économique 09:31:10–09:42:16 UTC. Parmi elles : 32 échecs, 33 inconnues/partielles, 8 swaps possibles par soldes mais sans référence de trade, 1 transfert, 1 wrap. Ces 8 ne reçoivent pas de montant USD ni de signal. Le troisième wallet n'a pas été interrogé pendant les limites fixées. |
| Marché archivé | 143 bougies quotidiennes closes (13 × 11) et 597 bougies de minute closes sur six candidats, horaires d'intervalle et **heure réelle de réception** conservés. Séries de minute parfois discontinues ; profondeur historique et quote exécutable absentes (`null`). Les quatre nouveaux pools n'ont chacun qu'un relevé prospectif. |
| Fomo | Zéro wallet `fomo_verified`. Formulaire local, import JSON, validation d'adresse et de preuve, boîte `pending_review`, export et revue explicite livrés. Le lien `/r/nobrainflip` est refusé comme preuve de wallet. |

Le [manifeste R2](../data/r2-20260926/manifest.json) fournit les 206 tentatives, leur source, requête, statut, heure, taille et SHA-256 ; `tx-selection.json` relie chaque signature aux références et réponses brutes ; `follow-checkpoint.json` contient les progrès, trois observations de trou (deux wallets distincts), l'inventaire **delta depuis couverture connue**, la position d'ouverture inconnue, et la raison d'arrêt. Le [détail de la cohorte](r2-wallet-cohort.md) relie chaque inférence à ses deux signatures. La sélection future devrait être figée avant une nouvelle période d'observation ; les données présentes ne sont pas hors échantillon.

## Horloges, marché et signaux

Les `blockTime` des transactions représentent l'heure économique. `raw_received_at` et les relevés de pool sont des heures réellement mesurées **pendant le backfill/suivi R2**, jamais une latence historique du bot avant ce lot. Les bougies quotidiennes historiques reçues le matin du 26 septembre ne sont pas rétroactivement disponibles pour une décision antérieure ; les rendements futurs B/A des trois inférences restent **`null`**. Un seul snapshot prospectif par coin ne suffit pas pour un ratio B/A longitudinal. Le moteur conserve donc un statut **données insuffisantes / aucune décision confirmée**, sans abaisser les seuils pour produire un signal. L'étude de séquences n'est pas une preuve de gains exécutables : profondeur passée, quote et impact restent inconnus.

Les quatre comparateurs logiciels du pilote (panier conservé, marché seul, wallets seuls, combinaison) restent disponibles et couverts par leurs tests, mais leur performance sur **R2 REAL** est `null` : les séries alignées, la profondeur et une période hors échantillon manquent. Aucun classement par rendement de ces variantes n'est publié.

Le [code officiel Raydium AMM v4](https://github.com/raydium-io/raydium-amm/blob/master/program/src/instruction.rs) justifie les tags 9/11/16/17 admis par le nouveau décodeur. Les routes Jupiter/Orca/CPMM et les divergences entre trade du pool et soldes du propriétaire restent partielles. Trois candidats initialement classables par instruction Raydium ont été **rétrogradés** parce que les mints/quantités du trade de référence ne correspondaient pas aux deltas du wallet ; ils ne deviennent ni transferts ni flux directionnels. Le décodeur R1 et ses fixtures restent séparés.

Les 18 transactions avec swap strict contiennent aussi d'autres programmes non décodés ; `complete` signifie **attribution bornée du swap de pool et de ses deux deltas propriétaire**, pas compréhension de chaque instruction de la transaction. Le rôle possible de ces programmes annexes mérite un audit avant une qualification de trader directionnel.

## Budget constaté et limites

| Période | Appels tentés | Collecte active | Coût facturé connu |
|---|---:|---:|---:|
| Audit initial | 120 | 643 s | 0 USD |
| Validation du worker | 5 | 31 s | 0 USD |
| Trois cycles supplémentaires fixés avant lancement | 81 | 458 s | 0 USD |
| **R2 total** | **206 / 2 000** | **1 132 / 1 800 s** | **0 USD** |

L'appel 54 à GeckoTerminal a reçu **HTTP 429** ; aucune relance en boucle ni autre endpoint de contournement n'a été utilisé. Un relevé unique a fonctionné lors du cycle ultérieur. L'audit initial a dépassé de **43 secondes** son sous-plafond interne de 10 minutes, à cause d'un limiteur par session sans compteur de phase ; le plafond utilisateur global de 30 minutes n'a pas été dépassé. Le budget R2 prend désormais en charge et teste des sous-plafonds de phase persistants entre commandes, à utiliser au lancement d'une nouvelle campagne ; il ne peut pas changer rétroactivement ce dépassement. Les cycles supplémentaires sont restés sous leurs 90 appels/600 s prévus. Un cycle s'est arrêté sur sa limite de temps, deux sur leur limite de transactions ; les checkpoints rendent cette interruption visible. La limite de 20 signatures par wallet peut masquer des événements plus anciens, signalés comme trous. Les 75 transactions de suivi ne sont pas un historique exhaustif de comptes de tokens, notamment fermés.

Le profil de 24 h et plusieurs jours du [plan](r2-collection-plan.md) **n'a pas été démarré** : à 15 minutes, 10 pools + 20 wallets demanderaient déjà environ 3 840 requêtes/jour avant les transactions. Quota durable gratuit, couverture historique des routes non prises en charge et coût d'un service soutenable restent inconnus. Aucune dépense payante et aucun ordre réel.

## Reproduction et statut

```bash
uv sync --frozen
uv run rotation r2-universe --root data/r2-20260926
uv run rotation r2-verify --root data/r2-20260926
uv run rotation r2-sequences --root data/r2-20260926
uv run pytest -q
cd web && npm ci && npm run build
```

Ces commandes de vérification ne font **aucun appel externe**. `r2-follow-once` en fait de nouveaux et consomme le budget partagé ; ne l'inclure que pour une campagne explicitement bornée. Statuts séparés : **logiciel R2 fonctionnel sur le corpus archivé ; couverture de cohorte et de marché insuffisante ; observation prospective de quelques minutes seulement ; rattachement Fomo non établi ; avantage financier non évalué**. Une CI verte ne change aucun de ces quatre derniers statuts.

Contrôles locaux du lot : **86 tests réussis**, Ruff lint/format sans écart, build TypeScript/Vite réussi. Les régressions R2 couvrent le corpus réel et dix audits de soldes, le replay répété, la reprise sans doublon, les limites de phase, la conservation FIFO, la mise en quarantaine des routes, l'absence de prix inventé, le refus des preuves Fomo de parrainage et l'isolement de l'API R2 réelle par rapport à DEMO. Ces contrôles valident du logiciel, pas l'hypothèse financière.

### Interface et services locaux à la clôture

L'API du présent worktree répond sur `127.0.0.1:8010` (Uvicorn PID 3178228) et le frontend sur `127.0.0.1:5175` (Vite PID 3156132, parent npm 3156099). L'univers, la cohorte, le checkpoint, une preuve réelle et une série de 13 bougies ont répondu en HTTP ; une URL de parrainage envoyée au formulaire a reçu HTTP 422. TypeScript/Vite build passe. Un test visuel Playwright n'a pas pu s'exécuter parce que Chrome/Chromium n'est pas installé dans cet environnement ; l'interface est servie localement, sans publication publique. Les services précédents sur 8008/8009/5173/5174 et PostgreSQL 55432 n'ont pas été modifiés ; **aucun worker de collecte** n'est actif. Pour arrêter uniquement les deux nouveaux serveurs, utiliser `Ctrl-C` dans leurs sessions de lancement ou confirmer les chemins de commande des PID ci-dessus puis arrêter ces PID/parents ; ne pas arrêter globalement un port. Les PID sont propres à cette session et seront différents après redémarrage.
