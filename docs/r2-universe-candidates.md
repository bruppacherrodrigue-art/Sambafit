# R2 — univers exploratoire Solana, 26 septembre 2026

Cette liste est une **proposition de recherche**, distincte d'une watchlist utilisateur et de toute recommandation d'achat. Le fichier exécutable est [`config/r2-candidates.json`](../config/r2-candidates.json) ; chaque ligne conserve son mint exact, son pool, son instant de connaissance et les numéros/hash des réponses archivées dans `data/r2-20260926/source/`.

## Règle fixée avant la sélection

Le [protocole R2](r2-collection-plan.md) exige un pool Solana exact, une réserve instantanée annoncée ≥ 100 000 USD, un volume glissant 24 h ≥ 25 000 USD, au moins 100 trades 24 h et dix bougies quotidiennes closes sur les quatorze derniers jours. Ces seuils déterminent seulement une continuité et une observabilité minimales ; ils ne mesurent ni la profondeur pour une taille d'ordre, ni la durabilité du marché, ni un rendement probable. Les hausses de prix récentes ne sont pas utilisées. L'ancienneté indiquée est la **création du pool primaire**, pas la création du token. L'ancienneté du token reste inconnue ici.

Les pools, réserves, volumes et comptes de trades proviennent des réponses publiques [GeckoTerminal API v2](https://api.geckoterminal.com/docs/index.html) reçues entre 09:00 et 09:03 UTC. Les 11 mints retenus ont été recoupés par `getAccountInfo` finalisé comme comptes `spl-token` de type mint. Les 11 séries quotidiennes ont chacune 13 clôtures admissibles. Les volumes 24 h sont **glissants et chevauchants** ; on ne les additionne pas. Les réserves sont des snapshots annoncés, pas une profondeur historique exécutable. Les prix du passé ne sont pas remplacés par les cotations actuelles.

| Candidat | Mint Solana exact | Pool primaire | DEX déclaré | Pool créé | Réserve USD relevée | Volume 24 h USD relevé | Statut |
|---|---|---|---|---|---:|---:|---|
| BONK | `DezXAZ8z7PnrnRJjz3wXBoRgixCa6xjnB7YaB1pPB263` | `5zpyutJu9ee6jFymDGoK7F6S5Kczqtc9FomP3ueKuyA9` | Orca | 2023-07-05 | 420 587 | 1 045 560 | research_candidate |
| WIF | `EKpQGSJtjMFqKZ9KQanSqYXRcF8fBopzLHYxdM65zcjm` | `EP2ib6dYdEeqD8MfE2ezHCxX3kP3K2eLKkirfPm5eyMx` | Raydium | 2023-11-20 | 6 864 107 | 899 626 | research_candidate |
| PENGU | `2zMMhcVQEXDtdE6vsFS7S7D5oUodfJHE8vd1gnBouauv` | `DdMA1cHcHEqYfttc1z1sJEY978CcU1pyjNuTWTNmdvzU` | Meteora | 2025-11-26 | 4 376 720 | 5 966 267 | research_candidate |
| POPCAT | `7GCihgDB8fe6KNjn2MYtkzZcRjQy3t9GHdC8uHYmW2hr` | `FRhB8L7Y9Qq41qZXYLtC2nw8An1RJfLLxRF2x9RwLLMo` | Raydium | 2023-12-12 | 4 307 263 | 326 259 | research_candidate |
| FARTCOIN | `9BB6NFEcjBCtnNLFko2FqVQBq8HHM13kCyYcdQbgpump` | `Bzc9NZfMqkXR6fz1DBph7BDf9BroyEf6pnzESP7v5iiw` | Raydium | 2024-10-18 | 9 277 415 | 1 564 930 | research_candidate |
| MEW | `MEW1gQWJ3nEXg2qgERiKu7FAFj79PHvQVREQUzScPP5` | `879F697iuDJGMevRkRcnW21fcXiAeLJK1ffsw2ATebce` | Raydium | 2024-03-26 | 10 499 172 | 234 557 | research_candidate |
| BOME | `ukHH6c7mMyiWCf1b9pnWe25TSpkDDt3H5pQZgZ74J82` | `DSUvc5qf5LJHHV5e2tD184ixotSnCnwj7i4jJa4Xsrmt` | Raydium | 2024-03-14 | 18 486 530 | 1 096 868 | research_candidate |
| PNUT | `2qEHjDLDLbuBgRYvsxhc5D6uDWAivNFZGan56P1tpump` | `4AZRPNEfCJ7iw28rJu5aUyeQhYcvdcNm8cswyL51AY9i` | Raydium | 2024-10-31 | 3 804 028 | 199 848 | research_candidate |
| GOAT | `CzLSujWBLFsSjncfkh59rUFqvafWcY5tzedWJSuypump` | `9Tb2ohu5P16BpBarqd3N27WnkF51Ukfs8Z1GzzLDxVZW` | Raydium | 2024-10-10 | 1 818 189 | 318 469 | research_candidate |
| GIGA | `63LfDmNb3MQ8mw9MtZ2To9bEA2M71kZUUGq5tiJxcqj9` | `4xxM4cdb6MEsCxM52xvYqkNbzvdeWWsPDZrBcTqVGUar` | Raydium | 2024-01-04 | 1 850 832 | 195 698 | research_candidate |
| MOODENG | `ED5nyyWEzpPPiWimP8vYm7sD7TD3LAt3Q3gRTWHzPJBY` | `22WrmyTj8x2TRVQen3fxxi2r4Rn6JDHWoMTpsSmn8RUd` | Raydium | 2024-09-10 | 3 168 510 | 408 450 | research_candidate |

**Candidat exclu conservé :** PUMP, mint `pumpCmXqMfrsAkQ5r49WcJnRayYRqmXz6ae8H7H9Dfn`, pool `2uF4Xh61rDwxnG9woyxsVQP7zuA6kLFpb3NvnRQeoiSd` (PumpSwap), parce qu'il s'agit du token d'une plateforme et non du type de coin spéculatif retenu pour cette étude. Son pool a été vu, mais son mint et sa série quotidienne n'ont pas été vérifiés par les appels R2 ; son export garde `decimals=null` et `closed_daily_candles=0` sans prétendre à une vérification négative. Les pages de pools émergents des tentatives 1–2 ont été écartées pour leur jeunesse/continuité non établie, sans constituer un inventaire exhaustif d'exclus. SOL/wSOL (`So11111111111111111111111111111111111111112`) et USDC (`EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v`) sont des actifs de transit/réserve, pas des candidats spéculatifs.

## Compatibilité de décodage, séparée de la sélection

Le corpus de transactions montre Raydium AMM v4, Orca, Jupiter, Meteora, Raydium CPMM et d'autres programmes. `r2_decode.py` reconnaît un swap AMM v4 à instruction documentée et deux variations SPL propriétaire/signataire concordant avec le trade de référence. Les tags 9/11/16/17 viennent du [code officiel Raydium AMM](https://github.com/raydium-io/raydium-amm/blob/master/program/src/instruction.rs). Le décodeur Meteora R1 reste disponible ; une route à étapes multiples est `partial_route` tant que sa comptabilité économique n'est pas prouvée. Un décodeur minimal suivant devrait couvrir d'abord les instructions Whirlpool/Jupiter réellement observées, le regroupement d'étapes et les variations SOL/wSOL, avec audits de soldes, versions et frais. Estimation de développement : environ 2–4 journées d'ingénierie et un corpus de régression diversifié, **pas** un coût de service autorisé ni une garantie de couverture.
