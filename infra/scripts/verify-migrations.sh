#!/usr/bin/env bash
# Prove that the schema migrations apply cleanly on pgvector/pgvector:pg16, using the real
# compose db service and the real api image.
#
#   infra/scripts/verify-migrations.sh
#
# Env: ATLAS_VERIFY_PROJECT (compose project, default atlas-verify), ATLAS_DB_PORT (host port
# for the db, default 55431), ATLAS_VERIFY_PYTEST (path to a python with pytest + atlas
# installed; when set, also runs the db-marked tests against the container).
# Starts only the db (plus a one-off api container), and always tears everything down.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT="${ATLAS_VERIFY_PROJECT:-atlas-verify}"
export ATLAS_DB_PORT="${ATLAS_DB_PORT:-55431}"
# The vault mount must exist for `compose run api`; the sample vault always does.
export VAULT_PATH="${VAULT_PATH:-$ROOT/samples/vault}"
# Migrations need no key; keeps Settings happy if anything reads it.
export ATLAS_EMBEDDINGS_ONLY=true

compose() {
  docker compose -p "$PROJECT" --project-directory "$ROOT" \
    -f "$ROOT/docker-compose.yml" -f "$ROOT/infra/compose.verify.yml" "$@"
}

cleanup() { compose down -v --remove-orphans >/dev/null 2>&1 || true; }
trap cleanup EXIT

fail() { echo "FAIL: $*" >&2; exit 1; }

echo "==> building api image"
compose build api

echo "==> starting db on 127.0.0.1:${ATLAS_DB_PORT}"
compose up -d --wait db

migrate() { compose run --rm --no-deps -T api python -m atlas.store.migrate; }

echo "==> first migration run"
first="$(migrate)"
echo "$first"
grep -q "applied 0001_init.sql" <<<"$first" || fail "0001_init.sql was not applied"

echo "==> second migration run (must be a no-op)"
second="$(migrate)"
[ -z "$second" ] || fail "second run applied something: $second"

psql_q() { compose exec -T db psql -U atlas -d atlas -tAc "$1"; }

echo "==> checking schema"
[ "$(psql_q "SELECT count(*) FROM pg_extension WHERE extname = 'vector'")" = "1" ] \
  || fail "pgvector extension missing"
for t in vaults clusters documents chunks topics document_topics wiki_links semantic_links link_feedback jobs schema_migrations; do
  [ "$(psql_q "SELECT to_regclass('public.$t') IS NOT NULL")" = "t" ] || fail "table $t missing"
done
[ "$(psql_q "SELECT count(*) >= 1 FROM vaults")" = "t" ] || fail "default vault not seeded"
echo "schema OK"

if [ -n "${ATLAS_VERIFY_PYTEST:-}" ]; then
  echo "==> db-marked tests against the container"
  py="$ATLAS_VERIFY_PYTEST"
  case "$py" in /*) ;; *) py="$PWD/$py" ;; esac
  ATLAS_VERIFY_PYTEST="$py"
  (cd "$ROOT/api" && ATLAS_TEST_DATABASE_URL="postgresql://atlas:atlas@127.0.0.1:${ATLAS_DB_PORT}/atlas" \
    "$ATLAS_VERIFY_PYTEST" -m pytest -q -m db)
fi

echo "PASS: migrations apply cleanly on pgvector/pgvector:pg16"
