# syntax=docker/dockerfile:1
# Atlas api + worker image (same image; the worker overrides CMD with `python -m atlas.worker`).

# ---- build stage: resolve and install dependencies into a self-contained venv
FROM python:3.12-slim AS build
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH
WORKDIR /src

# Dependencies first (cached until pyproject.toml changes): install against a stub package.
COPY pyproject.toml ./
RUN mkdir -p atlas && touch atlas/__init__.py \
 && pip install . \
 && pip uninstall -y atlas \
 && rm -rf atlas build *.egg-info

# Then the application itself (no dependency resolution needed).
COPY atlas ./atlas
RUN pip install --no-deps . \
 && cd / && python -c "import atlas.store.migrate as m; assert any(m.MIGRATIONS_DIR.glob('*.sql')), 'migrations missing from package'"

# ---- runtime stage: slim image, non-root user, no build tooling
FROM python:3.12-slim AS runtime
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    VAULT_ROOT=/vault \
    UPLOADS_ROOT=/uploads
# /uploads is owned by the app user so a fresh named volume mounted there inherits it.
RUN groupadd --system --gid 10001 atlas \
 && useradd --system --uid 10001 --gid atlas --home-dir /app --shell /usr/sbin/nologin atlas \
 && mkdir -p /app /vault /uploads \
 && chown atlas:atlas /app /uploads
COPY --from=build /opt/venv /opt/venv
WORKDIR /app
USER atlas:atlas
EXPOSE 8000

# api: apply migrations (idempotent, advisory-locked), then serve. The worker overrides this.
CMD ["sh", "-c", "python -m atlas.store.migrate && exec uvicorn atlas.http.app:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips '*'"]
