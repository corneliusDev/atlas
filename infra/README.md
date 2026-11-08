# infra

Everything needed to run Atlas with one `docker compose up`.

| File | What it is |
| --- | --- |
| `docker-compose.yml` (repo root) | `db` (pgvector/pgvector:pg16, also the job queue), `ollama` (embeddings only), `ollama-init` (one-shot `ollama pull nomic-embed-text`), `api` (migrations, then uvicorn on :8000), `worker` (same image, `python -m atlas.worker`), `web` (nginx on `127.0.0.1:3000`) |
| `docker-compose.host-ollama.yml` (repo root) | Override: use Ollama running natively on the host via `host.docker.internal:11434`; the ollama containers move to the inactive `bundled-ollama` profile |
| `api/Dockerfile` | Multi-stage `python:3.12-slim`, venv in `/opt/venv`, runs as uid 10001 |
| `web/Dockerfile`, `web/nginx.conf` | `node:22-alpine` Vite build, then `nginx:1.27-alpine`: SPA fallback, `/api/` proxied to `api:8000` |
| `infra/compose.verify.yml` | Overlay that publishes the db on `127.0.0.1:${ATLAS_DB_PORT:-55431}` for host-side tests |
| `infra/scripts/verify-migrations.sh` | Builds the api image, starts only the db, applies migrations twice (second must be a no-op), checks the schema, tears down |
| `infra/tests/test_infra.py` | Pytest checks of the rendered compose config, the override, the Dockerfiles and `nginx -t` |

## Usage

```bash
cp .env.example .env            # set ANTHROPIC_API_KEY (or ATLAS_EMBEDDINGS_ONLY=true) and VAULT_PATH
docker compose up               # UI at http://localhost:3000

# Native Ollama on the host (faster on macOS): `ollama pull nomic-embed-text` first, then
docker compose -f docker-compose.yml -f docker-compose.host-ollama.yml up

# Reset all data (index, queue, uploads)
docker compose down -v
```

Startup order: `db` healthy -> `api` (applies migrations, healthy once it serves
`/api/openapi.json`) -> `web`. The `worker` also waits for `ollama-init` to finish the model
pull, so the UI is reachable before the ~300 MB download completes.

## Checks

```bash
api/.venv/bin/python -m pytest -q infra/tests                       # needs the docker CLI
ATLAS_VERIFY_PROJECT=atlas-verify ATLAS_DB_PORT=55431 \
  ATLAS_VERIFY_PYTEST=api/.venv/bin/python infra/scripts/verify-migrations.sh
```
