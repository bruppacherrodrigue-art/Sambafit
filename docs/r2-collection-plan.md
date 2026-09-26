# R2 — protocole de sélection et budget, préenregistré le 26 septembre 2026

Ce document est fixé **avant les nouveaux appels de découverte et de collecte R2**. Il concerne un univers exploratoire Solana, pas la watchlist choisie par l'utilisateur. Aucun rendement ni signal confirmé n'est recherché par ajustement des seuils.

## Sélection des coins

Un candidat est identifié par son mint Solana exact, vérifié dans une source primaire du projet ou dans un registre public documenté puis recoupé avec le pool. SOL/wSOL et les stablecoins sont enregistrés comme réserve/transit, jamais comptés parmi les 8–12 coins spéculatifs visés. La présélection vise des noms déjà publics et des marchés vérifiables ; la hausse récente ne constitue pas un critère.

Pour retenir un coin comme `research_candidate`, le relevé doit montrer : (1) un pool exact Solana avec au moins 100 000 USD de réserve **instantanée annoncée** ; (2) au moins 25 000 USD de volume glissant 24 h et, si la source les donne, au moins 100 trades 24 h ; (3) au moins dix clôtures quotidiennes dans les quatorze derniers jours, sans assimiler des snapshots glissants à des bougies ; (4) une date de premier marché ou une ancienneté vérifiable, ou le statut `age_unknown` affiché. Ces seuils servent seulement à rendre l'échantillon observable ; ils ne décrivent ni sûreté, ni qualité d'investissement, ni durabilité sociale. Les candidats exclus et les champs manquants sont conservés. Une absence de profondeur historique laisse `historical_depth=null`.

Le programme de pool, le taux de décodage constaté et le coût d'un nouveau parseur sont des **champs séparés** du choix du coin. Un pool Raydium, Pump AMM, Orca ou Jupiter n'est pas exclu pour éviter un travail de décodage ; ses opérations restent partielles jusqu'à preuve suffisante.

## Découverte et cohortes

Pour chaque pool retenu, lire au plus dix références de trades récents de chaque côté quand elles sont disponibles, puis récupérer les transactions finalisées par signature. Ne pas chercher les swaps par adresse de mint. Un propriétaire de compte SPL n'est classé comme acteur potentiel que si le lien avec un signataire et les deltas nets est vérifié ; payeur, routeur, bénéficiaire et compte de pool restent séparés. Une activité exclusivement acheteuse est conservée avec `rotation_evidence=none`.

La sélection de cohorte R2 est datée après l'audit des transactions. Les fenêtres historiques antérieures sont étiquetées **exploratoires avec biais de sélection**. Les classements globaux et par coin n'emploient l'USD que si des prix passés admissibles pour les deux jambes existent ; les quantités sans prix restent `usd_non_comparable`. Les flux A→B spéculatifs, les entrées depuis réserve et les sorties vers réserve ont des compteurs distincts. Les entités liées possibles restent incertaines ; un acteur est plafonné à 10 000 USD par fenêtre agrégée, suivant l'hypothèse actuelle du moteur.

## Budget global du lot

**Dépense payante autorisée : 0 USD.** Plafond global persistant pour tous les lancements R2 : **2 000 requêtes HTTP/RPC tentées, retries compris, et 1 800 secondes de collecte active cumulée**. Les outils de documentation consultés sont consignés séparément comme lectures documentaires ; tous les appels de données passent par le budget partagé. Aucun changement d'endpoint ou de compte n'est utilisé pour contourner un 429. Un processus réserve son appel avant envoi, écrit la réponse ou l'échec, puis met à jour son checkpoint. `ROTATION_KILL_SWITCH=1` suspend tout nouvel appel. Le plafond fournisseur plus strict prévaut.

| Poste | Allocation maximale R2 | Premier audit borné |
|---|---:|---:|
| Découverte, mints, pools et trades | 220 appels | 30 appels |
| Transactions finalisées et suivi wallets | 1 200 appels | 50 appels |
| Prix, volumes, réserves et OHLCV | 380 appels | 30 appels |
| Marge d'erreur/rattrapage, sans relance automatique | 200 appels | 10 appels |
| **Total** | **2 000 appels** | **120 appels au plus** |

Le premier audit s'arrête dès qu'une source essentielle devient indisponible, sur quota, après erreurs répétées ou à 120 tentatives/10 minutes de collecte active. Son objectif est de vérifier la qualité des sources, pas de consommer le budget. Un second passage nécessite le même fichier de budget partagé et ne peut pas remettre les compteurs à zéro. Réserver au moins 100 appels du plafond global pour des relevés de marché synchronisés. Le manifeste R2 publie les appels tentés, réponses utiles, heures, hashes et erreurs.

Le pilote R1 est conservé séparément ; ses 69 appels et ses 60 transactions ne sont pas présentés comme des observations R2. Les nouveaux relevés seront dans `data/r2-20260926/` et dans un schéma PostgreSQL distinct de `DEMO` et de R1.

## Profil longue durée, **non démarré** dans ce lot

Pour 24 h, un cycle toutes les 15 minutes représente 96 cycles. Pour 10 pools, 10 suivis de marchés et 20 wallets, une interrogation individuelle par cycle ferait jusqu'à **3 840 appels/jour** (40 × 96), avant les transactions nouvelles et les retries ; ce profil excède le budget R2. À 30 minutes de cadence, le même ordre de grandeur est 1 920 appels/jour et reste trop proche du plafond, sans marge de rattrapage. À 1 minute par pool, dix OHLCV donneraient 14 400 relevés/jour, hors quotas gratuits présumés. Ces calculs sont des bornes d'appels, pas des devis fournisseur. À 2 Ko par réponse sommaire et 50 Ko par transaction pour 500 transactions/jour, prévoir environ 33 Mo/jour de JSON brut avant index et sauvegardes ; mesurer les tailles réelles avant dimensionnement. **Coût facturé connu : 0 USD pour les sources publiques testées ; coût et quota durable non établis.** Un service de plusieurs jours exige un quota documenté, une fréquence réduite ou un accès déjà autorisé, puis un budget nouveau à approuver.

Le service prévu est un worker local déclenché explicitement, avec sessions bornées, checkpoint, journal de trous, stockage du temps de réception réel et arrêt par `ROTATION_KILL_SWITCH=1` ou signal de terminaison. Aucun processus temporaire lancé ici ne sera décrit comme une observation de plusieurs jours.
