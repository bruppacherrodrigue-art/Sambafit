# Rotation Engine

Moteur local de recherche sur les rotations de capital Solana. Il lit des adresses publiques, conserve les réponses RPC et les opérations décodées, attribue les rotations, produit des signaux déterministes, rejoue une chronologie et simule un portefeuille. **Aucun chemin de code ne signe ni ne diffuse une transaction.** Le mode par défaut est une fixture `DEMO` synthétique.

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
