#!/usr/bin/env bash
set -Eeuo pipefail

ENV_FILE="${KB_PRODUCTION_ENV_FILE:-/etc/kb/production.env}"
APP_DIR="${KB_APP_DIR:-$(pwd)}"
requested_kb_image="${KB_IMAGE:-}"

if [ ! -f "$ENV_FILE" ]; then
  echo "Missing production env file: $ENV_FILE" >&2
  exit 1
fi

cd "$APP_DIR"

set -a
. "$ENV_FILE"
set +a

if [ -n "$requested_kb_image" ]; then
  KB_IMAGE="$requested_kb_image"
fi

: "${KB_IMAGE:?Set KB_IMAGE to the image tag that should be deployed.}"
: "${KB_ADMIN_API_KEY:?Set KB_ADMIN_API_KEY in the production environment.}"

export KB_IMAGE
export KB_PRODUCTION_ENV_FILE="$ENV_FILE"

API_URL="${API_URL:-http://127.0.0.1:8000}"
compose=(docker compose --env-file "$ENV_FILE" -f docker-compose.yml -f docker-compose.prod.yml)

echo "Validating production compose configuration..."
"${compose[@]}" config >/dev/null

echo "Pulling production image: $KB_IMAGE"
"${compose[@]}" pull app migrate worker eval-runner

echo "Starting Postgres..."
"${compose[@]}" up -d postgres

echo "Running database migrations..."
"${compose[@]}" run --rm migrate

echo "Restarting app and worker..."
"${compose[@]}" up -d --no-build app
"${compose[@]}" --profile worker up -d --no-build worker

echo "Waiting for health check..."
for attempt in 1 2 3 4 5 6 7 8 9 10 11 12 13 14 15 16 17 18 19 20 21 22 23 24 25 26 27 28 29 30; do
  if curl -fsS "$API_URL/health" >/dev/null; then
    break
  fi

  if [ "$attempt" = "30" ]; then
    echo "App did not become healthy at $API_URL" >&2
    exit 1
  fi

  sleep 2
done

echo "Checking readiness and worker runtime..."
curl -fsS "$API_URL/ready" >/dev/null
curl -fsS -H "X-KB-Admin-Key: $KB_ADMIN_API_KEY" "$API_URL/admin/jobs/runtime" >/dev/null

echo "Production deploy completed: $KB_IMAGE"
