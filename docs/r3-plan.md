# R3 — plan d'implémentation et preuves

Base vérifiée : `origin/main` à `486f55db6a0287ee6eca610a01c6afa61f184f00`, arbre propre, branche `feat/r3-memecoin-rotation-engine`. Aucun ordre réel. Les archives R2 restent intactes ; les sorties R3 ont leur propre répertoire et leur propre budget.

| Exigence | Code ciblé | Preuve attendue |
|---|---|---|
| C1, consommation FIFO même coin et hors univers | `reserve_fifo.py`, `engine.py`, `r2_sequences.py` | Régressions rouges avant correction puis vertes, conservation en unités de réserve, replay R2 comparé |
| Univers memecoin daté | `config/r3-universe.json`, `r3_registry.py`, migration 004 | Tests de mint exact, exclusions PUMP/JUP/réserves, date de connaissance |
| C2, signaux indépendants par paire | `signals.py`, `replay.py` | A seul et B/A seuls changent la décision ; paires simultanées conservées |
| C3, cohortes selon capital attribuable | nouveau classement sur références horodatées et opérations strictes | Classement reproductible, couverture et montants inconnus explicites |
| C4, collecte suivie jusqu'à décision | `r2_follow.py`, `r3_pipeline.py`, `api.py`, `R3Panel.tsx` | Pagination, priorité tournante, files persistées de signatures et d'enrichissement, reprise de RPC null, chaîne DEMO et arrêt réel visible |
| Identité et preuve des opérations | migration 005, `r2_sequences.py`, `r3_cohort.py` | Deux opérations pour une signature, manifeste SHA-256, audit indépendant des soldes |
| Budget R3 | budget distinct basé sur `r2_budget.py` | 2 000 tentatives, 1 800 s actifs, sous-plafonds et échéance HTTP testés |
| Validation | corpus R2, pilote R3 borné | archives inchangées, rapport avant/après, transitions réellement observées |

Ordre : (1) attribution et tests, (2) registre et signaux par paire, (3) sélection de cohorte, (4) suivi et pipeline, (5) replay, pilote borné, interface et rapport. Les paramètres seront fixés avant le pilote ; aucune calibration sur les résultats du pilote.
