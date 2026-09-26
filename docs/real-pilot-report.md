# Pilote réel borné — Solana, 26 septembre 2026

## Résultat et portée

Le lot valide une chaîne technique sur des réponses publiques réelles : trades de pools documentés → transaction Solana finalisée → décodeur versionné → variations SPL d'un propriétaire signataire → prix de bougies horodatées → réallocations typées → replay. Il **ne** valide pas une rotation entre deux memecoins, une cohorte Fomo, un portefeuille exécutable ou un avantage financier. Le jeu est un **univers technique** JUP/wSOL/USDC, distinct de toute watchlist personnelle. Le protocole a été [figé avant les appels](real-pilot-protocol.md).

| Mesure | Observation |
|---|---:|
| Dépense facturée | 0 USD |
| Requêtes source tentées | 69 : 62 RPC, 7 GeckoTerminal |
| Fenêtre d'appels | 06:29:58–06:42:49 UTC, 12 min 51 s ; plafond 120 appels / 90 signatures / 15 min |
| Signatures uniques tentées / transactions finalisées obtenues | 60 / 60 |
| Transactions v0 / v1 | 53 / 7 |
| Références de trades renvoyées par la source dans le prélèvement | 60 : 58 `buy`, 2 `sell` ; ces libellés décrivent le pool, pas forcément le trajet net du signataire |
| Swaps complets selon le décodeur prudent v4 | 18, chez 5 propriétaires signataires ; 16 sur les trois mints techniques |
| Autres opérations | 27 `unknown:partial`, 5 `unknown:partial_route`, 5 transferts, 5 wraps |
| Bougies réelles importées | 89 : JUP 30, wSOL 30, USDC 29 ; intervalles parfois non contigus |
| Rotations nettes valorisables du replay | 16 directes : entrées depuis USDC ou wSOL ; 0 entre deux coins spéculatifs, 0 inférée |
| Convergences agrégées | 3, séparées des attributions directes et avec indépendance incertaine |
| Signaux candidat/confirmé, épisodes avec issue | 0 / 0 |
| Wallets liés à Fomo | 0, aucune preuve d'adresse obtenue |

Les 60 réponses couvrent les blocs [450591978, 450594955] du 26 septembre 2026, entre 06:20:01 et 06:33:13 UTC. Le protocole avait prévu jusqu'à trois paires ; seuls les 30 premiers trades de chacun des pools exacts JUP/wSOL `C8Gr6AUuq9hEdSYJzoEpNcdjpojPZwqG5MtQbeouNNwg` et JUP/USDC `Et6HnPjetV8AzmxNAfzKJ6ax5VM82ZB7phY465Ns5iZW` ont été prélevés. Le pool wSOL/USDC n'a pas été audité dans cette fenêtre. Aucun wallet n'a été choisi après examen de sa performance future.

L'API [GeckoTerminal](https://api.geckoterminal.com/docs/index.html) a fourni les références de trades et OHLCV. Le premier RPC a été [l'endpoint public Solana](https://solana.com/docs/references/clusters) pour 11 transactions. Une requête v1 a d'abord échoué avec `-32015` car le client annonçait seulement v0 ; `maxSupportedTransactionVersion` a été corrigé à 1. Après 11 réponses, le RPC public a répondu HTTP 429. Le reste a été repris une fois sur [PublicNode](https://solana.publicnode.com/) avec le **même** budget persistant et un intervalle de 4 s. Deux tentatives RPC supplémentaires correspondent à l'erreur de version puis au 429 ; aucune boucle de relance automatique. La limite horaire du pilote a expiré sans nouvelle collecte.

## Preuve du décodage

Le décodeur v4 reconnaît les discriminants de swap du programme [Meteora DLMM](https://github.com/MeteoraAg/docs/blob/main/developer-guides/dlmm/index.mdx) `LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo`, comparés à son [IDL publié](https://github.com/MeteoraAg/dlmm-sdk/blob/main/idls/dlmm.json) v0.12.0, SHA-256 `045c0f4af044be046b6a14b350077e4242e8ac026b64a855803dab30fcdd8b35`. Un swap complet exige un seul discriminant de swap DLMM, une entrée et une sortie SPL nettes du **même propriétaire signataire**, aucune erreur d'exécution et des décimales cohérentes. Les frais sont lus dans `meta.fee`, séparément des deltas. Le payeur n'est jamais pris pour le trader par défaut.

Les [dix vérifications de champs bruts](manual-swap-checks.md) couvrent cinq adresses et comparent, pour chaque signature, instructions, propriétaire, signes des montants, unités de base, frais et unicité. Les dix concordent. Le manifeste contient pour les 60 signatures le slot, l'heure de bloc, l'heure de réception archivée, SHA-256 brut, programmes, rôles, version et statut ; [les réponses et la vérification](../data/real-pilot-20260926/manifest.json) permettent de reproduire le contrôle sans RPC. Les 18 swaps complets satisfont le critère déterministe du parseur, mais seuls dix ont fait l'objet de cette revue détaillée indépendante. Le dénominateur de **tous** les swaps réels parmi les transactions complexes reste incertain : `18/60` n'est pas un taux global de décodage des swaps.

Exemples sourcés : `5a6MpzMX…` montre +271,452511 JUP contre −0,784506780 wSOL au propriétaire signataire, avec 5 000 lamports de frais ; c'est une acquisition depuis wSOL, pas une rotation entre memecoins. `3iEGPkd…` montre −133,180798 USDC contre +382,638749 JUP et 5 139 lamports. `5H819ki…` contient deux swaps DLMM internes sous un programme parent non qualifié : les variations nettes sont lisibles, mais le regroupement économique reste `partial_route` et ne produit aucun flux de rotation. `2Mi4dLyg…` est une transaction v1 avec une seule jambe SPL attribuable et du SOL natif/flash composite ; elle reste partielle. Aucun échec on-chain n'était présent dans ces 60 signatures, donc ce cas reste couvert uniquement par fixtures synthétiques.

Les cinq adresses avec swap complet sont des **wallets candidats dans cet échantillon**. Trois ont des flux complets entre les mints techniques et un prix de bougie admissible : `MfDuWeq…` ≈ 3 777,99 USD sur 10 opérations, `GJvewf…` ≈ 399,40 USD sur 2, `4jjEXc…` ≈ 88,72 USD sur 4. Ces montants sont des minima de valeurs des deux jambes selon des bougies passées disponibles au moment du décodage, **pas** des prix exécutés, patrimoines, P&L, ni un classement des plus gros traders Solana. Les deux autres ont des sorties vers des mints hors univers et ne sont pas classables dans le sous-ensemble technique. Les liens entre ces adresses sont inconnus ; leur indépendance n'est pas présumée.

## Marché, replay et variantes

Les 89 observations sont des OHLCV USD de pools : JUP clôtures 04:48–06:28 UTC reçues à 06:30:48, wSOL clôtures 05:08–06:42 reçues à 06:42:40, USDC clôtures 06:04–06:42 reçues à 06:42:51. Le prix USDC est mesuré, jamais fixé à 1. Les intervalles ne forment pas tous une série minute continue ; l'accélération de volume n'est calculée que pour deux clôtures contiguës. La réserve de pool affichée lors de la découverte est une **mesure actuelle**, pas une profondeur historique. Aucune liquidité de bougie ni quote exécutable passée n'est importée.

La relecture [figée](../config/real-pilot.yaml) applique les dates de connaissance de l'univers et des candidats, la fenêtre inférée de 6 h et les directions `from_stable`, `from_reserve`, `to_stable`, `to_reserve`, `between_coins`. Elle produit 16 acquisitions directes valorisables, aucune vente suivie d'achat B attribuable, trois agrégats USDC/wSOL vers JUP ou wSOL et **zéro signal entre deux coins spéculatifs**. L'agrégat wSOL→JUP reste dominé par une seule adresse (concentration proche de 89,5 %) ; il ne prouve ni consensus indépendant ni mêmes dollars. Un achat isolé ne devient pas une rotation A→B. Le replay n'a donc ni confirmation, ni faux signal réel à invalider, ni horizon d'issue à mesurer. Les scénarios correspondants restent testés en synthétique et signalés comme tels.

Le temps de bloc est économique. L'heure de première réponse est mesurée pendant **ce** backfill, et le parseur v4 a été appliqué plus tard, vers 07:10 UTC. Il n'existe aucun horodatage du bot à l'époque des trades. Le décalage de 15–50 minutes entre bloc et décodage dans ce pilote mesure cette procédure de collecte et de correction, pas un délai historique d'alerte prospective. Le dernier relevé de marché précède la disponibilité des opérations v4. Aucune décision d'investissement ne peut être reconstruite comme si le bot était déjà présent lors du bloc.

Les quatre variantes sont exécutables sur fixture et figurent dans le [résultat JSON réel](../data/real-pilot-20260926/replay-result.json) avec même univers, période, capital initial de 1 000 USD et hypothèses de frais. Sur le corpus réel, panier : 3 intentions ; marché seul : 86 intentions de règle simple ; wallets seuls et combiné : 0 pendant la période où les bougies sont disponibles. **Toutes ont 0 remplissage, exposition 0, cash 1 000 USD, turnover 0 et rendement net `null`**, car la liquidité historique manque ; la période de marché se termine avant la disponibilité du décodage des wallets. Ce n'est ni un rendement nul observé ni une comparaison de performance. Aucune période finale hors échantillon exploitable n'existe dans ce prélèvement de minutes.

## Fomo, services et suite minimale

Les pages publiques [sociales](https://fomo.family/blog/learn/leveraging-fomos-social-features) et de [navigation](https://fomo.family/blog/learn/navigating-your-fomo-app) ont été consultées ; elles décrivent profils et classements, sans livrer dans les pages inspectées une liaison vérifiée profil → adresse ou un export documenté. L'application connectée n'a pas été inspectée. Cela **ne** démontre pas l'absence d'une voie autorisée. Pour rattacher un profil, il faut ouvrir ce profil dans Fomo connecté, relever l'adresse publique affichée ou un export autorisé si l'interface le permet, puis importer l'adresse avec URL/capture, date et niveau de confiance. Un pseudonyme ou un financement commun ne suffit pas. Aucun des candidats du pilote n'est appelé wallet Fomo.

Le pilote est importé dans le schéma PostgreSQL local `pilot_20260926`, séparé du schéma public de la démo. API pilote `127.0.0.1:8009`, tableau local `127.0.0.1:5174` ; les anciens services locaux de la livraison initiale restent sur 55432/8008/5173. **Aucun collecteur ni paper worker n'est actif.** L'API du pilote annonce `execution_enabled=false` et `kill_switch=true`. Dépense monétaire constatée : **0 USD** ; pas d'abonnement. Pour arrêter seulement la vue du pilote : `fuser -k 8009/tcp 5174/tcp`. Pour arrêter aussi les services Compose initiaux, lancer `docker compose --profile app down` depuis le dépôt initial ; cela conserve le volume PostgreSQL.

Entrées restantes : (1) mints choisis par l'utilisateur et adresses publiques Fomo prouvées si un rattachement Fomo est souhaité ; (2) couverture RPC durable et données de liquidité/quotes historiques horodatées si une évaluation d'exécution est voulue ; (3) observation prospective avec cohorte figée, épisodes indépendants et régimes variés. Aucun achat, ordre réel ou nouvel abonnement n'est autorisé par ce pilote.
