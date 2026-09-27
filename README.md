# Rotation Engine

Moteur local de recherche sur les rotations de capital Solana. Il lit des adresses publiques, conserve les réponses RPC et les opérations décodées, attribue les rotations, produit des signaux déterministes, rejoue une chronologie et simule un portefeuille. **Aucun chemin de code ne signe ni ne diffuse une transaction.** Le mode par défaut est une fixture `DEMO` synthétique.

## R3 : rotations entre memecoins Solana

Le [rapport de validation R3](docs/r3-validation-report.md) contient les preuves, compteurs et limites. Le [registre de recherche](config/r3-universe.json) classe les mints exacts avec provenance et date : dix memecoins candidats, PENGU incertain, réserves/transits et tokens de plateforme séparés. Il ne constitue pas une watchlist approuvée. La [politique FIFO](docs/r3-attribution-policy.md), la [règle de signal par paire](docs/r3-pair-signal-spec.md), la [cohorte](docs/r3-cohort-selection.md) et le [budget](docs/r3-collection-budget.md) sont versionnés.

Reproduction hors ligne depuis les archives réelles R2/R3, sans nouvel appel réseau de données :

```bash
uv sync --frozen
uv run rotation r3-cohort
uv run rotation r3-replay
uv run rotation r3-process-follow
uv run rotation r3-manifest
uv run rotation r3-budget
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
cd web && npm ci && npm run build
```

Le [manifeste R3](data/r3-20260927/manifest.json) répertorie 24 signatures présélectionnées et 16 transactions prospectives, avec hashes et statuts. Le replay trouve cinq **inférences exploratoires** entre memecoins sur 20 swaps stricts ; les cinq décisions restent en observation faute de marché A/B connu à l'heure utile. Le suivi prospectif contient une seule opération de swap complète, hors univers cible, et zéro rotation cible. Les quatre rendements comparatifs sont `null`. Aucun wallet Fomo n'est vérifié et aucun gros trader durable n'est qualifié.

Pour consulter l'onglet **R3 réel** en local, lancer le backend depuis la racine du présent worktree :

```bash
ROTATION_SCHEMA=pilot_20260926 ROTATION_KILL_SWITCH=1 uv run uvicorn rotation.api:app --host 127.0.0.1 --port 8011
```

Dans un second terminal :

```bash
cd web
VITE_API_PROXY_TARGET=http://127.0.0.1:8011 npm run dev -- --host 127.0.0.1 --port 5176
```

Ouvrir `http://127.0.0.1:5176/`, onglet **R3 réel**. Les preuves publiques et heures de réception sont consultables ; la démo reste isolée. Arrêter ces deux processus par `Ctrl-C` dans leurs terminaux ou par leurs PID identifiés. Aucun worker périodique n'est lancé par le tableau de bord. Les commandes `r3-audit`, `r3-follow-once` et `r3-market-follow` font de nouveaux appels externes et consomment le budget persistant ; le kill switch les bloque.

## Pilote réel reproductible du 26 septembre 2026

Le [rapport du pilote](docs/real-pilot-report.md) décrit un prélèvement technique de 60 transactions finalisées et 89 observations de marché : 18 swaps complets selon un décodage DLMM prudent, 32 opérations partielles, 5 transferts, 5 wraps. Il ne constitue ni une watchlist utilisateur ni une cohorte Fomo. Les réponses brutes et leurs SHA-256 sont dans [le corpus](data/real-pilot-20260926/manifest.json). Les cinq adresses avec swap complet restent **on-chain non attribuées à Fomo**. Il n'y a pas de signal réel confirmé ni de P&L exécutable.

Pour rejouer **sans nouvel appel externe**, dans ce worktree :

La base PostgreSQL de la livraison initiale écoute déjà sur `127.0.0.1:55432` dans l'environnement remis. Si elle est arrêtée, lancer `docker compose up -d db` depuis un seul des deux dossiers du projet avant les commandes ci-dessous ; ne pas essayer de démarrer deux bases sur le même port.

```bash
uv sync --frozen
uv run rotation pilot-audit --corpus data/real-pilot-20260926
ROTATION_SCHEMA=pilot_20260926 uv run rotation pilot-import --corpus data/real-pilot-20260926
ROTATION_SCHEMA=pilot_20260926 uv run rotation demo-seed
ROTATION_SCHEMA=pilot_20260926 uv run rotation replay --config config/real-pilot.yaml
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
```

`pilot-import` est idempotent, conserve les temps de réception et de décodage **mesurés pendant le pilote** et isole ce corpus dans `pilot_20260926`. `pilot-verify --corpus ...` recalcule les preuves et réécrit le manifeste ; `pilot-audit` est en lecture seule. Les transactions reçues après la sélection technique restent exploratoires, car les wallets candidats ont été identifiés dans le même échantillon.

Une **nouvelle** collecte technique est volontaire et crée son propre corpus ; elle ne reproduit pas les mêmes signatures que celui du 26 septembre :

```bash
uv run rotation pilot-collect --output data/mon-nouveau-pilote --per-pool 30
uv run rotation pilot-audit --corpus data/mon-nouveau-pilote
ROTATION_SCHEMA=mon_nouveau_pilote uv run rotation pilot-import --corpus data/mon-nouveau-pilote
```

`pilot-collect` fixe avant le premier appel les plafonds de **120 tentatives, 90 transactions et 15 minutes**, avec 0 USD de dépense autorisée, et les conserve dans `budget.json`. Le même répertoire reprend ses fichiers sans refaire un appel déjà archivé ; changer `--per-pool` pendant une reprise est refusé. Un résultat `unavailable` reste explicite et n'est pas relancé implicitement. Le corpus gelé fourni ici a déjà atteint sa limite de temps : cette commande n'a pas été relancée dessus. L'opérateur peut définir `SOLANA_RPC_URL` pour un RPC public qu'il est autorisé à utiliser ; la commande par défaut emploie le RPC public Solana et s'arrête en cas de quota. Aucun abonnement n'est activé.

Pour ouvrir la vue privée sur un autre port que la démo initiale :

```bash
ROTATION_SCHEMA=pilot_20260926 ROTATION_MODE=REAL ROTATION_KILL_SWITCH=1 uv run uvicorn rotation.api:app --host 127.0.0.1 --port 8009
```

Dans un deuxième terminal :

```bash
cd web
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8009 npm run dev -- --host 127.0.0.1 --port 5174
```

Ouvrir `http://127.0.0.1:5174`, choisir **Réel → Opérations**, puis ouvrir une signature. La fiche montre les deux horloges, les soldes du propriétaire, le prix de clôture disponible, la direction et la décision. **Démo** reste une fixture séparée. Arrêter uniquement les processus Uvicorn/Vite de ce worktree avec `Ctrl-C` dans leurs terminaux ou leurs PID identifiés. Aucun worker de collecte n'est lancé par ces commandes.

## R2 : univers, cohorte et suivi borné

Le [nouvel univers de recherche](docs/r2-universe-candidates.md) propose 11 coins spéculatifs à mint exact ; il n'est pas la watchlist approuvée de l'utilisateur. Le [classement de cohorte](docs/r2-wallet-cohort.md) est limité aux swaps effectivement attribuables dans l'échantillon. Les profils Fomo ont un [parcours de preuve distinct](docs/r2-fomo-linking.md). Le [rapport R2](docs/r2-report.md) distingue données réelles, routes partielles et métriques indisponibles.

Reconstruction **hors ligne et sans nouvel appel de données** depuis les réponses et hashes archivés :

```bash
uv sync --frozen
uv run rotation r2-universe --root data/r2-20260926
uv run rotation r2-verify --root data/r2-20260926
uv run rotation r2-sequences --root data/r2-20260926
uv run rotation r2-budget --root data/r2-20260926
uv run pytest -q tests/test_r2_real_corpus.py tests/test_r2_sequences.py tests/test_r2_fomo.py tests/test_r2_follow.py
```

Le corpus R2 reste dans `data/r2-20260926/` et n'écrit pas dans les tables PostgreSQL du pilote R1. `cohort.json`, `sequences.json`, `tx-selection.json`, les réponses `source/` et `raw/`, ainsi que `follow-checkpoint.json` portent la provenance. `sequences.sqlite` conserve les ventes en attente et les allocations entre sessions. Toute reconstruction de la cohorte garde sa date de connaissance et marque l'analyse passée comme exploratoire. Une vente ne finance jamais plusieurs achats au-delà de son montant attribuable.

Un **nouveau** cycle de suivi fait de vrais appels et consomme le même `budget.json` global de 2 000 tentatives/1 800 secondes actives, avec 0 USD de dépense payante autorisée. Il relève d'abord un pool, puis les signatures et transactions des wallets strictement qualifiés ; il s'arrête avec un checkpoint et un motif visible. Aucun service longue durée ne démarre automatiquement :

```bash
uv run rotation r2-follow-once --root data/r2-20260926 --wallets 3 --pools 1 --transactions 10
```

Le suivi par adresse du wallet ne reconstitue pas à lui seul les comptes de tokens fermés. Les nouvelles opérations sans référence de trade restent sans USD et ne rejoignent pas le classement strict. Un snapshot de pool porte son heure de réception et un volume **glissant 24 h**, jamais une profondeur historique ou une bougie indépendante. La collecte s'arrête par `ROTATION_KILL_SWITCH=1` avant tout nouvel appel, par épuisement de limite, ou en terminant la commande. Le [budget et le profil de plusieurs jours non activé](docs/r2-collection-plan.md) détaillent les quotas.

Pour le tableau de bord R2 local, lancer l'API du **présent worktree** dans un terminal, puis le frontend dans un second :

```bash
ROTATION_SCHEMA=pilot_20260926 ROTATION_MODE=REAL ROTATION_KILL_SWITCH=1 uv run uvicorn rotation.api:app --host 127.0.0.1 --port 8010
```

```bash
cd web
npm ci
VITE_API_PROXY_TARGET=http://127.0.0.1:8010 npm run dev -- --host 127.0.0.1 --port 5175
```

Ouvrir `http://127.0.0.1:5175/`, onglet **R2 réel**. Le formulaire de preuves Fomo crée seulement des dossiers `pending_review`. Aucun ordre réel n'est disponible. Arrêter avec `Ctrl-C` dans **ces** deux terminaux ; si lancés autrement, identifier leurs PID et chemins de commande avant `kill`, sans interrompre les services d'autres projets.

## Démarrage local

Pré-requis : Docker Compose, Python 3.12, [uv](https://docs.astral.sh/uv/), Node 22 et npm. Depuis ce dossier :

```bash
docker compose up -d db
uv sync --frozen
uv run rotation doctor
uv run rotation demo-seed
uv run rotation replay --config config/experiment.yaml
uv run rotation paper --config config/paper.yaml
uv run uvicorn rotation.api:app --host 127.0.0.1 --port 8008
```

Dans un deuxième terminal :

```bash
cd web
npm ci
npm run dev
```

Ouvrir `http://127.0.0.1:5173`. Les contrôles d'administration et les ports restent sur `127.0.0.1`. Pour un lancement Compose complet : `docker compose --profile app up --build -d`; arrêter avec `docker compose --profile app down` (le volume de base est conservé). Aucun worker de collecte ne démarre automatiquement.

## Données et commandes

`config/coins.json` et `config/wallets.json` sont vides volontairement. Chaque coin exige son mint Solana, ses decimals et sa date d'éligibilité. Une attribution Fomo exige une preuve datée ; un pseudonyme seul ne suffit pas. L'interface accepte les imports JSON, la CLI accepte JSON/CSV :

```bash
uv run rotation import-watchlist --file config/coins.json
uv run rotation import-wallets --file config/wallets.json
uv run rotation import-market --file chemin/vers/barres.csv
uv run rotation audit-data --config config/research.yaml
uv run rotation backfill --config config/research.yaml
uv run rotation collect --config config/research.yaml
uv run rotation replay --config config/experiment.yaml
uv run rotation paper --config config/paper.yaml
uv run rotation report --run-id UUID
```

Les deux imports vides retournent une erreur utile. `audit-data` fait au plus deux appels RPC de contrôle ; `backfill` et `collect` retournent `missing_wallets` sans liste. La collecte est plafonnée par `max_calls`, `max_wallets`, `max_pages` et `max_minutes` ; `ROTATION_KILL_SWITCH=1` arrête les nouveaux tours. La collecte en direct est un polling borné que l'opérateur relance ; aucun processus temporaire n'est présenté comme durable.

Les trois horloges sont `economic_at` (bloc), `available_at` (vu par le moteur) et `decoded_at` (version du parseur disponible). Les décisions exigent des données `finalized`. Le modèle des prix utilise seulement une bougie close et disponible avant la décision ; faute de prix ou liquidité, la décision reste en observation. Les corrections sont versionnées. Les réponses brutes, leur hash, la source et le parseur sont stockés en PostgreSQL. Les sommes sont en `Decimal`/`NUMERIC` et les quantités de tokens en unités de base entières.

Le replay produit des révisions `DEMO` ou `REPLAY`, jamais des alertes historiques étiquetées `PAPER LIVE`. Le mode `REPLAY` du tableau montre les révisions historiques issues des données `REAL`. Les résultats de `DEMO` et `REAL` sont séparés par des colonnes de provenance et des filtres d'API. La simulation emploie la prochaine bougie close disponible et des hypothèses de frais/impact explicites ; elle ne mesure pas un P&L exécutable sans quotes et profondeur historiques. Le score sur 100 est une hypothèse explicable, pas une probabilité de gain.

## Tests et arrêt

```bash
docker compose up -d db
uv run ruff check src tests
uv run ruff format --check src tests
uv run pytest -q
cd web && npm ci && npm run build
```

Arrêter les terminaux Uvicorn/Vite avec `Ctrl-C`, puis `docker compose down`. Pour supprimer aussi les données locales, utiliser explicitement `docker compose down -v` après sauvegarde. Les migrations SQL sont dans `src/rotation/migrations`; la migration 002 possède un script inverse.

## Périmètre de preuve

Voir [l'audit des sources](docs/data-audit.md), [le plan et la matrice](docs/plan.md), [le rapport pilote](docs/pilot-report.md) et [la qualification](docs/qualification.md). Les paramètres de démarrage ne sont pas calibrés pour la rentabilité. Aucun classement de « meilleurs wallets Fomo » vérifiable ni lien profil → adresse publique n'a été obtenu ; le moteur peut recevoir des wallets publics avec preuves plus tard. La couverture actuelle ne permet aucune conclusion sur l'hypothèse financière.
