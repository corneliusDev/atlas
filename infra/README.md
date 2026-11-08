# infra

Placeholders for deployment pieces owned by the infra track:

- `docker-compose.yml` lives at the repo root (services: db, ollama, api, worker, web; profile `host-ollama`).
- `api/Dockerfile` (FROM python:3.12-slim), `web/Dockerfile` (node:22-alpine build -> nginx:1.27-alpine).
- `infra/nginx.conf`: serve the SPA, proxy `/api` to `api:8000`.
- `infra/ollama-pull.sh`: pull `nomic-embed-text` on first start.
