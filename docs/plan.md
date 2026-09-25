# Plan de livraison et matrice de preuve

Conception approuvée par le cahier des charges utilisateur. Le moteur sépare quatre frontières : acquisition de données, opérations économiques conservatrices, décisions déterministes à deux horloges, et simulation isolée. Un résultat non décodable reste inconnu et ne devient pas un swap. Le mode par défaut est DEMO, sans ordre réel.

| Exigence | Implémentation livrée / lacune | Preuve |
|---|---|---|
| L0 Audit borné et budget | `docs/data-audit.md`, `rotation doctor`, plafonds par commande | Deux réponses RPC de contrôle ; lien Fomo non vérifié |
| L1 Registres et collecte | Imports, migrations, RPC HTTP plafonné, checkpoints, bruts et trous ; comptes clos non couverts | Tests de reprise et contrat RPC borné |
| L1 Normalisation | Soldes SPL entiers, classification prudente, frais et erreurs ; SOL natif et routes complexes incomplets | Tests de swap, transfert, wrap et décodage partiel |
| L2 Rotations | Attribution directe/inférée et convergence agrégée, conservation des ventes, groupes plafonnés | Tests de conservation et double comptage |
| L2 Décisions | Features disponibles à l'instant, score versionné, états et révisions ; persistance de portefeuille non qualifiée | Tests de non fuite temporelle et déduplication |
| L3 Replay | Même moteur, horloge de disponibilité, étude descriptive et portefeuille papier ; témoins appariés et comparaison des quatre politiques non livrés | Replay déterministe, échantillon DEMO insuffisant |
| L4 Interface | API privée locale, modes DEMO/REAL/REPLAY, preuves et trous ; PAPER LIVE continu non automatisé | Compose et proxy locaux vérifiés |
| L5 Qualification | Rapport logiciel / données / avantage distincts | `rotation report`, `docs/pilot-report.md`, `docs/qualification.md` |

Ordre : créer d'abord le schéma et les contrats de test, puis collecter et normaliser, ensuite attribuer, décider, rejouer et exposer. Chaque étape doit fonctionner sans Fomo ni clés. Une expérience réelle reste non qualifiée avant historique de marché, cohortes datées et liquidité historique. La démo n'active aucune collecte réelle au lancement.

## Décisions initiales

- Python 3.12, FastAPI et PostgreSQL 16 via Compose. Les valeurs monétaires utilisent `Decimal` et les quantités de tokens des entiers.
- Un seul processus local pour l'API et des commandes CLI séparées pour les jobs bornés. PostgreSQL persiste les checkpoints et décisions ; pas de queue externe.
- Frontend React/TypeScript local. Accès API limité au loopback et contrôles administratifs non publiés.
- Les seuils et coûts sont hypothétiques et versionnés. Aucune conclusion de rentabilité issue des fixtures.
