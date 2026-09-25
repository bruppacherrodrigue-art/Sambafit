# Audit des données — 2026-09-25

Le périmètre initial est Solana. Deux requêtes de contrôle ont été faites sur l'adresse publique du programme de vote Solana (`Vote111...`) : `getSignaturesForAddress` a renvoyé une signature finalisée au slot 450453184, puis `getTransaction` a renvoyé ses soldes, frais, instructions et statut. Cette adresse n'est pas un trader et ces appels ne constituent pas un pilote de stratégie. Aucun wallet candidat ni mint de watchlist n'a été fourni. Aucune collecte massive n'a commencé.

| Donnée requise | Source officielle/documentée | Accès disponible | Profondeur historique | Précision temporelle | Limites / coût | Statut | Alternative | Lacune résiduelle |
|---|---|---|---|---|---|---|---|---|
| Profil Fomo → adresse Solana | [Guide social Fomo](https://fomo.family/blog/learn/leveraging-fomos-social-features), [guide de l'app](https://fomo.family/blog/learn/navigating-your-fomo-app) | Pages publiques, aucun compte fourni | Non documentée | Date de vérification manuelle | Gratuit pour ces pages | Pages lues, lien non testé | Import manuel de preuve et d'adresse publique | Aucun lien profil → wallet vérifié ; pseudonyme insuffisant |
| Classement Fomo longue période | [Annonce officielle de Fomo Web](https://fomo.family/blog/announcing-fomo-web) | Fomo confirme des classements sur plusieurs périodes ; aucun tableau de rangs public accessible dans les pages consultées | Non établie | Inconnue | Compte Fomo nécessaire d'après l'annonce | Non testé dans l'app | Import manuel daté d'un export/capture autorisé | Aucun « meilleur wallet » fiable ne peut être listé aujourd'hui ; un classement de P&L n'est pas le critère de capital réalloué |
| Export ou API Fomo | Mêmes pages officielles | Aucune API/export officiel trouvé dans les pages consultées | Non documentée | Inconnue | Inconnu | Non testé | Import JSON/CSV local | Découverte automatique Fomo indisponible |
| Signatures d'adresse | [getSignaturesForAddress](https://solana.com/docs/rpc/http/getsignaturesforaddress) | RPC public principal joignable | Dépend de l'historique conservé par le nœud ; 90 jours non garantis | `blockTime` secondes ou null ; slot | [Limites du RPC public](https://solana.com/docs/references/clusters), changeables ; 0 $ constaté | 1 réponse réelle finalisée | RPC dédié déjà autorisé, si fourni | Adresse du wallet seule ne couvre pas toujours ses comptes de tokens, surtout fermés |
| Transaction, soldes, frais, erreurs | [getTransaction](https://solana.com/docs/rpc/http/gettransaction), [structures JSON](https://solana.com/docs/rpc/json-structures) | RPC public principal joignable | Selon nœud ; non mesurée sur 90 jours | `blockTime` secondes ou null ; `first_seen_at` local | Même quota ; 0 $ constaté | 1 transaction de vote réelle testée | Import de réponses RPC archivées | Décodage de swaps et comptes fermés à qualifier sur vrais wallets |
| Flux continu | [logsSubscribe](https://solana.com/docs/rpc/websocket/logssubscribe) | Aucun service durable configuré | Direct uniquement ; rattrapage HTTP requis | Observation locale mesurable | Filtre `mentions` : une adresse par abonnement ; quota fournisseur | Contrat lu, non testé en direct | Polling HTTP borné avec checkpoint | Latence et coupures réelles non mesurées |
| Prix, volume, bougies | Aucun fournisseur de marché fourni | Import CSV/JSON local | Selon fichiers fournis ; zéro ici | Selon source et clôture fournie | 0 $ actuellement | Non testé sur données réelles | Fixtures DEMO explicitement synthétiques | Étude historique réelle et fraîcheur du marché impossibles |
| Liquidité/profondeur et quotes historiques | Aucun fournisseur documenté fourni | Aucun | Zéro | Inconnue | Inconnu | Non testé | Hypothèses de coût séparées | P&L exécutable impossible à établir |

## Règles d'accès et de conservation

- Plafond par commande réelle : 100 appels RPC et 30 minutes, maximum 1 000 appels et 2 heures de collecte par jour ; zéro achat et zéro dépense autorisée. Les valeurs sont configurables vers le bas. Aucun job de collecte ne démarre automatiquement avec la démo.
- Confirmation de décision : `finalized`. Les signatures provisoires peuvent être observées mais ne déclenchent aucune décision. Polling de rattrapage après arrêt ; les trous et échecs sont enregistrés.
- Réponses brutes utiles : JSON conservé 30 jours par défaut, avec SHA-256, URL de source sans secret, horodatage de réception et version du parseur. Les opérations, preuves et révisions dérivées restent conservées pour audit. Une purge explicite est requise.
- La pagination de l'adresse du wallet ne prouve pas la couverture des comptes SPL. Une collecte qualifiée exige l'inventaire daté des comptes de tokens, le traitement de comptes fermés et une mesure de couverture. Sans cela, l'état est `partial` et les signaux sont suspendus.
- Les prix et la liquidité doivent avoir `observed_at <= decision_at` et `period_end <= decision_at`. Les données de démo ne sont jamais étiquetées historiques.

## Accès manquants

1. 10–20 mints Solana choisis avec dates d'éligibilité et un jeu de prix/volumes/quotes historiques horodatés, si disponible.
2. 30–50 adresses publiques candidates et, pour tout lien Fomo revendiqué, URL/capture ou autre preuve datée et vérifiable.
3. Éventuel accès RPC déjà payé/autorisée avec politique d'historique et quotas, et éventuel fournisseur de liquidité historique.
