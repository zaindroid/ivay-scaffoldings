#!/bin/sh
# Runs on the VPS, from /opt/ivay-pilot, after the tarball is unpacked. Idempotent.
set -eu
cd /opt/ivay-pilot/deploy/pilot
PILOT_HOST="${PILOT_HOST:-srv1900484.hstgr.cloud}"

# Secrets are generated once on the server and never leave it.
if [ ! -f .env ]; then
  umask 077
  printf 'POSTGRES_PASSWORD=%s\nIVAY_WEBHOOK_SECRET_SHOP_DEV=\nPILOT_HOST=%s\n' \
    "$(openssl rand -hex 24)" "$PILOT_HOST" > .env
  echo "created .env"
fi

docker compose up -d --build --wait
# Seed (or update) the shop row with the public URLs. The api image has the DB driver.
set -a; . ./.env; set +a
docker run --rm --network ivay-pilot_internal -v /opt/ivay-pilot:/app:ro -w /app \
  -e DATABASE_URL="postgresql+asyncpg://ivay:${POSTGRES_PASSWORD}@postgres:5432/ivay" \
  -e IVAY_PUBLIC_BASE="https://${PILOT_HOST}" \
  ivay-pilot-api python scripts/seed_dev.py
docker compose ps
