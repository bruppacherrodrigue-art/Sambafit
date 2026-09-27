# R3.1 — plan d'exécution

Base : `feat/r3-memecoin-rotation-engine` au `2f0aced054583c7618bba7a1ca79d65357c1a84f`, identique à la tête distante de la PR #1 ; `main` au `486f55db6a0287ee6eca610a01c6afa61f184f00`. Arbre propre. Aucun AGENTS.md du dépôt. Les archives R2/R3 restent intactes ; sorties R3.1 dans `data/r3-1-20260927/`.

## Tâches et preuves

1. **Horloges T1.** Ajouter les régressions dans `tests/test_r31_temporal.py`, vérifier l'échec `candidate` pour un flux économique vieux de sept jours, puis corriger `signals.py` avec un âge économique et un retard d'observation versionnés. Vérifier bornes et dates futures. Propager aux flux agrégés et au comparateur wallet.
2. **Révisions T2.** Reproduire dans `tests/test_r31_temporal.py` la vente, l'achat B et le rachat tardif A. Corriger `replay.py` pour comparer les paires actives avant/après chaque lot, émettre une annulation à T+4, fermer l'épisode et permettre son expiration par horloge explicite. Vérifier doublons, redémarrage et corrections simultanées.
3. **Connaissance T3.** Tester le redécodage tardif de `refresh_follow_state` sur réponse brute locale. Ajouter une horloge injectable, un journal de révisions de décodage et une disponibilité effective. `process_follow` utilise cette disponibilité ; `price_operations` et le replay n'utilisent un prix qu'après réception, sans déplacer l'heure économique. Vérifier une correction de prix tardive.
4. **Référence de stratégie.** Créer `docs/strategy-spec.md` et `config/strategy-r3-1.json` avant le replay. Implémenter qualification causale de range, admission d'actifs et wallets avec raisons manquantes, et préparation paper avec risques/coûts explicites. Brancher le même verdict dans le replay et le suivi, sans transformer un `research_candidate` en actif simulable.
5. **Preuves et interface.** Rejouer R2/R3 hors réseau dans `data/r3-1-20260927/`, comparer les états et horloges ; exposer les révisions et admissions dans `/api/r3-1/*` et l'onglet local. Écrire `docs/r3-1-validation-report.md`, vérifier toute la suite, Ruff, build, puis pousser la PR #1 toujours en brouillon et contrôler la CI du nouveau SHA.

Chaque correction suit test rouge → code minimal → test vert ; les étapes de documentation n'affirment que les comportements vérifiés. Aucun appel de collecte n'est nécessaire.
