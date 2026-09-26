# Écarts vers un pilote réel — audit du code du 26 septembre 2026

Base vérifiée : `54cbbee9638aae8b7ed1191672af94fbca945bbf`, branche `feat/rotation-engine`, dépôt propre. Les 36 tests initiaux utilisent des fixtures synthétiques ; aucune ne prouve un swap réel. Cette matrice est révisée après le pilote, sans confondre capacité logicielle et résultat empirique.

| Exigence | Chemin de code | Preuve existante | Statut initial | Correction nécessaire |
|---|---|---|---|---|
| Réponses Solana finalisées et pagination | `solana.SolanaRpc`, `collect.backfill_wallet` | Contrat RPC sur 1 vote ; tests avec faux RPC | Implémenté non validé sur données réelles de swaps | Collecter un corpus de signatures de trades et publier compteurs, erreurs, checkpoints |
| Opérations normalisées issues de la collecte | `collect.backfill_wallet` → `SolanaDecoder.decode` → `Store.add_operation` | 36 tests, tous synthétiques | Implémenté non validé sur données réelles | Vérifier au moins 10 opérations contre soldes et instructions bruts |
| Programmes et versions | `solana.SolanaDecoder` | Legacy/v0 seulement ; allowlist Jupiter dans `config/research.yaml` | Partiel | Documenter programmes du corpus ; inconnu si version/programme non couvert |
| Signataire, payeur, propriétaire et bénéficiaire | `solana._balances` sélectionne `owner == wallet` | Aucun test réel ; payeur ignoré dans la décision | Partiel | Séparer rôles, rejeter attribution ambiguë, ne jamais inférer trader du payeur seul |
| Swap routé et instructions internes | `SolanaDecoder.decode` classe sur présence d'un programme et deux deltas SPL ; `engine.attribute_rotations` crée une rotation | Tests synthétiques de route | Partiel | Réconcilier comptes et mouvements internes ; documenter routes complexes non couvertes |
| SOL natif, wSOL, frais et échecs | `SolanaDecoder.decode` lit SPL et `meta.fee` ; ignore `preBalances/postBalances` | Tests wrap et échec synthétiques | Partiel | Rapprocher SOL natif, frais et création/fermeture de comptes ; distinguer les cas non sûrs |
| Prix, volume et liquidité réels | `Store.add_market_bar`, `cli.import-market` | Fichiers importés ou fixture DEMO ; aucune source connectée | Absent | Adaptateur de marché documenté, OHLCV et relevés de liquidité horodatés |
| Trois niveaux de rotation | `engine.attribute_rotations`, `aggregate_convergence` | Tests synthétiques ; agrégat absent du replay et de l'API | Partiel | Conserver les trois preuves séparées dans le corpus et la vue |
| Marché à l'instant et B/A | `signals.market_features`, `research.price_operations` | Position de fourchette, rendement, volume relatif d'un coin ; pas B/A, volatilité ni SOL | Partiel | Ajouter contexte B/A et qualité temporelle sans inventer les données manquantes |
| Replay strictement temporel | `replay.replay`, `Store.list_operations` | Tests d'absence de bougie future et versions de décodeur | Implémenté et testé | Marquer la latence historique hypothétique, figer cohortes/watchlist connues à chaque décision |
| Quatre variantes comparables | Aucun comparateur ; `paper.simulate_paper` consomme le replay combiné | Aucun test | Absent | Panier, marché seul, wallets seuls, combiné sur mêmes bars/capital/coûts |
| Paper trading et exécution | `paper.PaperBook`, `simulate_paper`, `cli.paper` | Ordres fictifs sur fixture ; pas de signal prospectif connecté | Partiel | Comparateurs et statut d'exécution inconnu sans profondeur historique ; aucun ordre réel |
| Fomo → wallet | `Store.import_wallets`, `wallet_profile_links` | Validation de preuve datée seulement ; [pages sociales Fomo](https://fomo.family/blog/learn/leveraging-fomos-social-features) lues | Implémenté non validé sur données réelles | Garder profils prouvés distincts des candidats on-chain ; action manuelle dans l'app si nécessaire |
| Vue d'une transaction réelle | `api.evidence`, `web/src/main.tsx` | Fiche de preuve DEMO ; pas de chronologie réelle accessible sans signal | Partiel | Liste d'opérations réelles ouvrable par signature avec rôles, soldes, statut et chronologie |
| Budget et reprise | `SolanaRpc.calls`, `collect`, `checkpoints` | Tests synthétiques de checkpoint ; pas de budget partagé multi-source/durée de backfill | Partiel | Budget global tentatives, transactions uniques, durée et manifeste persistant |

Les [pages officielles Fomo](https://fomo.family/blog/learn/navigating-your-fomo-app) consultées décrivent la recherche de profils et le classement dans l'application. Elles ne documentent pas, dans leur contenu public inspecté, un export de liaison profil → adresse. Cela ne démontre pas l'absence d'une voie autorisée dans l'application connectée. Aucun profil Fomo n'est attribué dans ce pilote.

## État après correction et pilote

Le [rapport réel](real-pilot-report.md), les [dix contrôles bruts](manual-swap-checks.md) et le manifeste figé fournissent les preuves précises. Les statuts ci-dessous remplacent les statuts initiaux pour cette branche ; « testé » signifie testé sur le périmètre indiqué, jamais sur tout Solana.

| Exigence | Chemin de code | Preuve existante | Statut | Correction nécessaire |
|---|---|---|---|---|
| Collecte avec budget et reprise | `pilot.PilotBudget`, `collect_corpus`, `SolanaRpc` | 69 tentatives sous cap, 60 bruts hashés, reprise après `-32015` et 429, test d'idempotence | Implémenté et testé | Service prospectif durable et plafonds fournisseur à qualifier séparément |
| Swaps normalisés | `solana.SolanaDecoder`, `real_corpus.import_corpus`, `Store.add_operation` | 18 swaps complets, 10 contrôles de champs bruts, 32 partiels, révision v4 archivée | Implémenté et testé | Plus de programmes et comptes fermés pour améliorer la couverture |
| Versions et programmes | `SolanaRpc.transaction`, discriminants DLMM dans `solana.py` | 53 v0 et 7 v1 récupérées ; IDL Meteora vérifié ; v1 complexe reste partiel | Partiel | Décoder les routes Jupiter et le SOL natif sans fusionner des intentions |
| Payeur, signataire et propriétaire | `SolanaDecoder.decode`, `independent_balance_audit`, manifeste | Rôles distincts ; propriétaire signataire requis ; dix contrôles | Implémenté et testé | Bénéficiaires, délégations et comptes fermés dans les cas ambigus |
| Routes et instructions internes | `SolanaDecoder.decode`, `partial_route` | Cinq transactions multi-swap quarantinées ; aucune fausse rotation | Partiel | Prouver le regroupement Jupiter/route avant de classer complet |
| Prix et volumes réels | `market.GeckoClient`, `parse_candles`, `import_corpus` | 89 bougies USD horodatées, trois mints, intervalles non contigus | Implémenté et testé | Série prospective plus longue et alignée ; volumes cumulés gardés séparés |
| Liquidité / profondeur historique | `PoolInfo.reserve_usd` spot ; `MarketBar.liquidity_usd=None` | Réserve spot non réutilisée pour le passé ; quatre variantes bloquées | Partiel | Quotes et profondeur historiques pour tailles d'ordre, sinon P&L non évalué |
| Preuves directes, inférées, agrégées | `engine.attribute_rotations`, `aggregate_convergence`, `replay.ReplayResult`, API | 16 acquisitions directes ; trois agrégats séparés ; zéro inférée dans ce corpus ; tests de conservation | Partiel | Corpus longitudinal de ventes puis achats attribuables |
| Features de marché et ratio B/A | `signals.market_features`, `research.price_operations`, `study_events` | Prix, fourchette, rendement et volume de bougies closes ; aucune paire A/B spéculative mesurable | Partiel | Ratio B/A, volatilité, régime SOL et alignement sur séries longues |
| Replay et dates de connaissance | `replay.replay`, `config/real-pilot.yaml`, `Store.list_operations` | Relecture identique, 60 opérations, sélection datée, aucune donnée future dans décision | Implémenté et testé | Cohortes prospectives et partition finale intacte pour qualification |
| Quatre variantes | `comparison.compare_variants`, CLI replay | Quatre règles exécutées sur fixture ; quatre lignes réelles `net_return=null`, cash/exposition/turnover publiés | Implémenté et testé | Données comparables et liquidité historique avant un P&L |
| Paper live | `paper.simulate_paper`, CLI `paper` | Simulation synthétique et blocage sans liquidité ; aucun collecteur actif alimentant paper | Partiel | Worker prospectif relié aux relevés et alertes persistées |
| Fomo → adresse | `Store.import_wallets`, table de preuves | Import prouvé possible ; zéro liaison vérifiée | Implémenté non validé sur données réelles | Inspection autorisée d'un profil connecté et preuve datée |
| Vue d'opération réelle | `api.operation_context`, `api.evidence`, onglet Opérations | Parcours Firefox : signature réelle → soldes → marché → décision ; DEMO/REAL isolés | Implémenté et testé | Affiner affichage des comptes techniques et de l'incertitude des routes |
