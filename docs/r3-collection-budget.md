# R3 — budget fixé avant tout nouvel appel

Budget global distinct de R2 : `data/r3-20260927/budget.json`, **2 000 tentatives externes au maximum, retries compris ; 1 800 secondes cumulées de collecte active ; 0 USD payant**. Le fichier et son verrou sont persistés entre commandes. Les limites du fournisseur plus strictes prévalent.

Répartition initiale maximale, conservatrice : 24 `getTransaction` pour les références ≥500 USD présélectionnées (phase `cohort_audit`, 300 s, 30 appels) ; 20 appels pour un cycle de suivi paginé de quelques wallets (phase `prospective_follow`, 300 s, 40 appels) ; 12 appels marché/pools et bougies coordonnées (phase `market_follow`, 180 s, 20 appels). Le reste du plafond reste **non autorisé automatiquement** pour ce pilote. Un appel HTTP a un timeout ajusté au temps restant ; un sleep de limitation n'a lieu que si la durée restante le permet. Un HTTP 429 arrête la phase et laisse une raison de reprise ; aucune alternance de comptes ou d'endpoints pour contourner la limite.

Le rattrapage et le suivi s'effectuent sur les wallets présélectionnés/validés, avec un ordre tournant persistant. Les archives R2 sont utilisées en premier et ne consomment aucun appel R3. Les nouvelles réponses, y compris les erreurs et les null, portent un numéro de tentative, hash, heure de réception et statut. Une transaction null reste en attente réessayable.

Le profil de collecte longue n'est pas démarré dans R3. Pour 10 pools et 10 wallets à 15 minutes : 1 920 requêtes de base par jour, avant pagination, transactions et bougies ; à 10 secondes entre appels GeckoTerminal, les pools seuls demanderaient environ 9,6 heures de temps réparti par jour. La capacité gratuite durable et le coût facturé d'un service adapté restent inconnus ; aucune dépense n'est engagée.
