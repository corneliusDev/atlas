# Atlas

Local-first Markdown knowledge graph. Spec: [`docs/PRD.md`](docs/PRD.md) (the "Data flow design"
section is the signed-off design).

## Layout

```text
api/                  Python 3.12 + FastAPI (api and worker share one image)
  atlas/types.py      NewTypes, closed unions (IngestJob, IngestOutcome, IngestError, Link, NodeRef...), value types
  atlas/ports.py      Protocols: JobQueue, VaultScanner, IngestPipeline, EmbeddingModel, LanguageModel,
                      DocumentRepository, ClusterRepository, LinkFeedbackRepository, SearchService, GraphService
  atlas/config.py     Settings (env)
  atlas/pipeline/     IngestPipeline + pure functions (markdown, chunking, scoring, clustering)
  atlas/models/       Ollama embedding adapter, Anthropic language-model adapter
  atlas/store/        Postgres repositories, JobQueue, migrations/*.sql + migrate.py
  atlas/read/         SearchService, GraphService
  atlas/http/         FastAPI app (app.py) + DTOs (dto.py)
  atlas/testing/      In-memory fakes of every write-side port
  atlas/worker.py     Worker loop + VaultScanner (python -m atlas.worker)
  tests/
web/                  React + Vite + Sigma.js UI; src/api/openapi.json is the API contract
samples/vault/        50 sample notes across 5 themes (+ a latin-1 file, a .png and a .txt that must be ignored)
docs/                 PRD and generated openapi.json
scripts/              export_openapi.py, gen_sample_vault.py
infra/                deployment placeholders
```

## Dev commands

```bash
# Python env (host has 3.14; the image uses 3.12 - deps are pinned for both)
cd api && python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'
.venv/bin/pytest -q                       # unit + contract tests (no Docker needed)
.venv/bin/mypy                            # strict type check of atlas/

# Postgres + migrations
docker run -d --name atlas-dev-db -e POSTGRES_DB=atlas -e POSTGRES_USER=atlas -e POSTGRES_PASSWORD=atlas \
  -p 5432:5432 pgvector/pgvector:pg16
.venv/bin/python -m atlas.store.migrate postgresql://atlas:atlas@localhost:5432/atlas
ATLAS_TEST_DATABASE_URL=postgresql://atlas:atlas@localhost:5432/atlas .venv/bin/pytest -q -m db

# Run the API locally
.venv/bin/uvicorn atlas.http.app:app --reload --port 8000     # docs at /api/docs

# Run the worker locally (scan VAULT_ROOT, drain the queue, recluster, exit). Env: DATABASE_URL,
# OLLAMA_URL, VAULT_ROOT, UPLOADS_ROOT, WORKER_CONCURRENCY (default 2), ATLAS_EMBEDDINGS_ONLY.
ATLAS_EMBEDDINGS_ONLY=1 VAULT_ROOT=../samples/vault .venv/bin/python -m atlas.worker --exit-when-idle

# Regenerate the OpenAPI contract after changing routes/DTOs (repo root)
api/.venv/bin/python scripts/export_openapi.py

# Full stack
cp .env.example .env && docker compose up                      # UI at http://localhost:3000
```
