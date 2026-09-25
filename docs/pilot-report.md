# Rapport du pilote initial — 2026-09-25

## Données réelles

Le seul essai réel est un contrat RPC borné de **deux appels** sur le programme de vote Solana : une signature finalisée au slot 450453184 et la réponse `getTransaction` correspondante. Cette adresse est un contrôle technique, pas un wallet de trader. Période historique des traders couverte : **aucune**. Wallets Fomo attribués : **0**. Mints surveillés réels : **0**. Transactions de traders réels analysées : **0**. Taux de décodage de swaps réels : **non mesurable**. Quotes, prix et profondeur historiques : **0 observation**. Coût monétaire constaté : **0 $** (RPC public et ressources locales déjà présentes).

L'audit Fomo a trouvé une mention officielle de classements sur plusieurs périodes, sans export ou liaison publique vérifiable entre rang et adresse Solana. Il serait trompeur de publier une liste de « meilleurs wallets » fondée sur des pseudonymes ou sur le P&L seul. Une capture ou un export autorisé, daté, accompagné de preuves d'adresse serait nécessaire pour cette liste.

## Démo synthétique

La fixture `DEMO` contient trois opérations synthétiques et dix bougies synthétiques au total pour A/B. Elle démontre deux rotations directes, des révisions candidate/confirmée/invalidée et un cas de marché insuffisant. Le replay reproductible a produit 3 révisions et un seul épisode distinct ; les horizons de 1, 2 et 3 minutes ont chacun une seule issue, donc aucun intervalle fiable. La simulation papier a produit 2 remplissages, un cash final synthétique de 925,018... pour 1 000 initiaux et `executable_pnl=false`. Les transactions, les prix et le portefeuille de cette section sont **inventés pour les tests**. Aucune courbe ou rendement de la démo ne démontre un avantage financier.

## Statuts

| Dimension | Statut |
|---|---|
| Logiciel local exécutable | Oui, sur fixture et PostgreSQL local |
| Contrat RPC HTTP réel | Testé sur une transaction de contrôle |
| Couverture historique de traders | Insuffisante |
| Étude historique qualifiée | Non commencée |
| Avantage supplémentaire wallets + marché | Non évalué |
| Observation prospective | Non démarrée |
| Exécution réelle | Désactivée |

Les contrôles automatisés vérifient des invariants de code et des scénarios synthétiques. Ils ne valident ni l'attribution des comptes Fomo, ni la couverture de comptes SPL fermés, ni une capacité d'exécution réelle.
