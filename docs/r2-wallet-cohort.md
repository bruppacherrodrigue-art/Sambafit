# R2 — cohorte candidate observée dans l'échantillon

La sélection est **exploratoire et rétrospective**, figée dans `data/r2-20260926/cohort.json` après la collecte du 26 septembre 2026. Elle ne prétend pas désigner les plus gros traders de Solana ni les meilleurs comptes sur le long terme. Aucun wallet n'est attribué à Fomo. Les mints et leurs pools se trouvent dans [l'univers R2](r2-universe-candidates.md).

## Méthode reproductible

Les tentatives source 37–47 ont lu les trades publics des 11 pools primaires. Les 300 références retournées par pool ont servi de vivier ; le corpus sélectionne de façon déterministe les **trois premiers achats et les trois premières ventes** de chaque pool, soit 66 signatures uniques et 36 adresses de payeur/acteur annoncées par la source. Ce choix donne une couverture régulière par pool mais **pas** une couverture exhaustive des trades. `getTransaction` finalisé a récupéré les 66 signatures. Le classement strict n'admet un wallet que si son adresse est à la fois propriétaire des comptes SPL affectés et signataire, si le programme/instruction est pris en charge, si les deux deltas de soldes et les quantités de la référence concordent à 1 % près, et si la transaction n'est pas échouée. Le payeur de frais seul n'est pas assimilé au trader ; routeur, compte de pool et bénéficiaire restent distincts dans la preuve brute.

Le résultat strict est **18 swaps complets chez 3 wallets**, couvrant 07:05:48–09:07:30 UTC. Les 48 autres signatures comprennent 30 routes partielles, 15 décodages partiels et 3 programmes non pris en charge. Le dénominateur des vrais swaps économiques parmi ces 48 n'est pas établi ; aucun taux de décodage global n'est publié. Dix swaps complets sont recomptés indépendamment à partir des arrays de soldes RPC, des signataires, des instructions et des frais dans `manual_balance_audits`. Les réponses et hashes sont conservés dans le manifeste. Aucun détenteur, pool ou profil social n'a été promu par simple taille de solde.

L'USD par trade est le `volume_in_usd` **estimé par GeckoTerminal pour la transaction horodatée**, admis uniquement quand les quantités `from/to` correspondent aux deltas du propriétaire. Il s'agit d'un proxy d'activité observée, pas d'une valorisation de portefeuille ni d'un prix de remplissage futur. Les montants de tokens sans cette preuve valent `null` en USD et ne sont pas comparés. Les positions antérieures, le patrimoine total, la durée de détention et les liens entre personnes restent inconnus. La formule d'inférence FIFO utilise la même réserve wSOL, six heures et `min(vente restante, achat restant)` ; elle ne prouve pas l'identité des fonds. `SequenceStore` conserve les événements, ventes restantes et allocations entre sessions et reconstruit dans l'ordre économique de façon idempotente. Aucun signal confirmé n'est rétrodaté à partir de cette reconstruction.

## Classement global strict par USD réalloué observé

| Wallet public, on-chain non attribué | Swaps complets | USD de trades observés, proxy | USD attribués à A→B via wSOL | Qualification |
|---|---:|---:|---:|---|
| `CreQJ2t94QK5dsxUZGXfPJ8Nx7wA9LHr5chxjSMkbNft` | 4 | 1 999,01 | 499,19 | inconnue ; vente GOAT puis achat BOME |
| `MfDuWeqSHEqTFVYZ7LoexgAK9dxk7cy4DFJWjWMGVWa` | 13 | 2 247,45 | 347,54 | automatisation/arbitrage probable : ≥10 swaps complets en <1 h ; identité inconnue |
| `9nXDunV8eNvYSVys7JSBkm2hz9Q79Q3EYeko19srVeMC` | 1 | 284,12 | 0 | vente isolée PNUT ; destination inconnue dans le corpus |

Le classement n'est comparable **qu'à l'intérieur de cet échantillon de références et de programmes décodables** ; même là, les pools ne sont pas couverts uniformément dans le temps. Les mesures par coin (`buys_usd`, `sells_usd`, `swaps`, flux net calculable) figurent dans `cohort.json` sous `per_coin_ranking`. Les adresses techniquement annoncées parmi les 36 références, mais sans swap strict décodé, restent des pistes non qualifiées, jamais ajoutées pour atteindre artificiellement la cible 20–40. La première vente observée n'établit pas le début de possession ; `holding_duration=null` et `opening_position_unknown=true`.

## Trois réallocations inférées, aucune directe entre coins

| Wallet | Vente source et preuve | Achat destination et preuve | USD attribués | Lecture |
|---|---|---|---:|---|
| `CreQJ2t9…` | GOAT, `4pQG8HgSavyYhWr91rshM8JKQKNbMLWAkFW1A5L6eLcbDENWCtdBn6s8WvjV4maS7SUCmsamBCq1crubQjZv1fwe` | BOME, `YaMV6bDniwL1MDTayRdVRfqdNZNLRXqP5wppeJFu3CkyV3BuppWi4JXZoZY5dAiAi9NYwJg96UehcmRLfDvnCCg` | 499,19 | transit wSOL, ordre temporel |
| `MfDuWeqS…` | MOODENG, `4uKJ1Ho1z6cnrdf7KHF9NgEAw2cDCHqdESgmnL8E5AAdA7k1MjWBobMWZ1crYXP95ZAgHEq559o5zrZgGjKqrE6f` | FARTCOIN, `2u8SnXU1t1hetukFfHSHh7LwPH82BABDM34rKCndr7jjCBWDLCLQpKHqKLPSL9EMN5CWnAHCtF98fijNL5iNyQt7` | 298,16 | reste de l'achat non financé par cette vente |
| `MfDuWeqS…` | PNUT, `5NoCoNGjYoHiecsNDr83Z7JNStVXTbfT8dW4q3qk3V4yz6htgSNfAnPAymcZErHhKogV9FKUVEYFL1w1hjfHdLij` | MOODENG, `5xTLiJF7PVTjy2sf2sAB7qFfkSMF4rLPJu2PNvbvTjpj9jV5aAtJHmmvGVv7Vj3u2EVx45rVtpeqPWM9CE8cYYGZ` | 49,38 | reliquat de vente non réutilisé |

Les autres entrées depuis wSOL/USDC sont des **acquisitions depuis la réserve**, les sorties vers wSOL/USDC sans achat ensuite sont des **sorties sans destination connue**. Zéro swap direct A→B spéculatif et zéro convergence agrégée vérifiée dans ce corpus. La cohorte étant sélectionnée après observation de ces opérations, ces trois appariements ne sont pas un test hors échantillon ni un indice de profit.
