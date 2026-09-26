# Protocole préenregistré du pilote technique — 26 septembre 2026

Ce document fixe le prélèvement et les règles avant les appels de données du pilote. Il ne remplace pas la watchlist de l'utilisateur et n'est pas une recommandation d'achat.

## Univers technique et découverte

- Réseau Solana mainnet. Mints exacts : wSOL `So11111111111111111111111111111111111111112` ([explorateur Solana](https://explorer.solana.com/address/So11111111111111111111111111111111111111112/metadata)), USDC natif `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` ([Circle](https://help.circle.com/support/en/usdc-supported-blockchains-minting-redemption-faqs?id=kb_article_view&sysparm_article=KB0010590)), JUP `JUPyiwrYJFskUPiHa7hkeR8VUtAeFoSYbKedZNsDvCN` ([Jupiter Research](https://discuss.jup.ag/t/jup-minting-and-accountability/464)). JUP est retenu pour la vérifiabilité du mint et des marchés publics ; aucune rentabilité n'est présumée.
- Source de découverte : [GeckoTerminal Public API](https://api.geckoterminal.com/docs/index.html), pools JUP/wSOL, JUP/USDC et wSOL/USDC s'ils existent. Sélection déterministe : pour chaque paire exacte, pool public avec la plus grande réserve USD annoncée lors de la découverte, puis tri lexicographique de l'adresse. Le pool est un contexte, pas un wallet trader.
- Échantillon : au plus 30 trades récents par pool, dans l'ordre renvoyé, signatures uniques ; puis `getTransaction` finalisé. Le hash de trade sert de candidat ; aucun `getSignaturesForAddress` sur le mint. Les propriétaires SPL qui sont aussi signataires et présentent des deltas compatibles deviennent des **wallets candidats dans l'échantillon**, sans attribution Fomo. Les autres rôles restent séparés et peuvent être inconnus.

## Budget et arrêt

- Dépense payante autorisée : **0**. Aucun abonnement, aucune clé privée.
- Un lancement : **120 requêtes externes tentées au plus**, retries compris, **90 transactions uniques au plus**, **15 minutes au plus**. Les plafonds du fournisseur plus stricts prévalent. La documentation publique GeckoTerminal annonce une limite approximative de 10 appels/minute sur sa référence actuelle ; le pilote attend au moins 10 secondes entre ses appels GeckoTerminal et cesse sur 429. RPC Solana : au plus 1 appel/seconde, arrêt sur limite ou réponse ambiguë. Aucun relancement automatique pour contourner le budget.
- Répartition maximale prévue : 3 appels de découverte, 3 listes de trades, 3 OHLCV, 3 relevés de pools, 90 transactions RPC, 21 appels de marge. Un échec consomme une tentative. La commande publie tentatives par source, transactions uniques, durée et checkpoints. Un arrêt laisse un manifeste reprenable avec budget nouveau explicite.
- Les services Compose existants n'effectuent aucune collecte. Le pilote se lance manuellement. `ROTATION_KILL_SWITCH=1` interdit son départ.

## Temps, prix et preuve

- `blockTime` est le temps économique. L'heure de récupération pendant ce backfill est la disponibilité **observée aujourd'hui**, jamais le délai de réception historique du bot. Un replay historique ne peut employer que des scénarios déclarés de retard ; aucune latence historique réelle n'est revendiquée.
- [OHLCV GeckoTerminal](https://api.geckoterminal.com/docs/index.html) fournit des bougies de pool. Seules les bougies closes avant une décision et déjà disponibles selon le scénario sont admissibles. Les prix USD sont conservés avec pool, intervalle, source, réception et précision. Un volume de 24 h glissant du pool reste un relevé cumulatif, jamais une bougie indépendante. La réserve actuelle ne remplace pas la liquidité historique.
- La valorisation d'un swap ancien nécessite une bougie USD historique admissible ou une autre source historique vérifiée. USDC garde son prix mesuré, sans parité USD imposée. Sans valorisation, rotation quantitative USD et paper fill sont inconnus ou bloqués selon le cas.
- Décodage de référence : lecture indépendante des instructions internes, des comptes SPL pré/post et des soldes SOL pré/post, avec payeur, signataires, propriétaires et bénéficiaires distincts. Une route agrégée donne au plus une opération économique par wallet et transaction. Échec, transfert, LP et attribution ambiguë ne deviennent pas des swaps. Les versions non supportées restent inconnues.

## Analyses fixées avant résultat

- Fenêtre inférée A→B : **6 heures** par wallet, ventes consommées FIFO, aucune réutilisation. Convergence agrégée : même fenêtre, groupes conservateurs, jamais présentée comme les mêmes fonds. JUP→wSOL est une sortie vers actif de marché, JUP→USDC une sortie stable ; USDC→JUP est une acquisition, pas une rotation de deux memecoins.
- Replay de trois niveaux de preuve et signaux `observing/candidate/confirmed/invalidated/expired`, score hypothétique déjà versionné. Les états renforcés ne sont jamais rétrodatés. Les variantes exploratoires sont étiquetées.
- Comparaison logicielle des quatre politiques sur les mêmes périodes, même univers, même capital initial et mêmes hypothèses de coûts. Sans profondeur historique, statut **non exécutable**. Aucune optimisation des seuils après inspection.
- Contrôle manuel d'au moins 10 swaps réels si 10 existent. Le dénominateur « tous les swaps » reste indéterminé si la source de référence n'est pas exhaustive ; pas de taux global trompeur. Cible technique 30 swaps / environ 5 wallets, sans forcer une conclusion si l'accès gratuit la rend impossible.
