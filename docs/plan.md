# Plan de livraison et matrice de preuve

Conception approuvée par le cahier des charges utilisateur. Le moteur sépare quatre frontières : acquisition de données, opérations économiques conservatrices, décisions déterministes à deux horloges, et simulation isolée. Un résultat non décodable reste inconnu et ne devient pas un swap. Le mode par défaut est DEMO, sans ordre réel.

| Exigence | Implémentation prévue | Preuve attendue |
|---|---|---|
| L0 Audit borné et budget | `docs/data-audit.md`, `rotation doctor`, plafonds de config | Réponses RPC de contrôle, coût et lacunes publiés |
| L1 Registres et collecte | Imports de mints/wallets, schéma versionné, RPC HTTP plafonné, checkpoints, bruts et trous | Tests de reprise et contrat RPC borné |
| L1 Normalisation | Soldes entiers, classification conservatrice, frais et erreurs | Fixtures de swap, transfert et décodage partiel |
| L2 Rotations | Attribution directe/inférée/agrégée sans réutiliser les ventes, groupes plafonnés | Tests de conservation et double comptage |
| L2 Décisions | Features disponibles à l'instant, score versionné, états et révisions | Tests de non fuite temporelle et déduplication |
| L3 Replay | Même moteur, horloge de disponibilité, signaux témoins, coûts de simulation | Replay déterministe et bilan d'incertitude |
| L4 Interface | API privée locale, dashboard DEMO/REPLAY/PAPER LIVE, preuves et trous | Démarrage local et contrôle d'isolation |
| L5 Qualification | Rapport logiciel / données / avantage distincts | `rotation report` et bilan documenté |

Ordre : créer d'abord le schéma et les contrats de test, puis collecter et normaliser, ensuite attribuer, décider, rejouer et exposer. Chaque étape doit fonctionner sans Fomo ni clés. Une expérience réelle reste non qualifiée avant historique de marché, cohortes datées et liquidité historique. La démo n'active aucune collecte réelle au lancement.

## Décisions initiales

- Python 3.12, FastAPI et PostgreSQL 16 via Compose. Les valeurs monétaires utilisent `Decimal` et les quantités de tokens des entiers.
- Un seul processus local pour l'API et des commandes CLI séparées pour les jobs bornés. PostgreSQL persiste les checkpoints et décisions ; pas de queue externe.
- Frontend React/TypeScript local. Accès API limité au loopback et contrôles administratifs non publiés.
- Les seuils et coûts sont hypothétiques et versionnés. Aucune conclusion de rentabilité issue des fixtures.
