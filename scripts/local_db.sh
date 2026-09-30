#!/usr/bin/env bash
# Docker-free Postgres for dev/test: starts the system cluster and creates the
# ivay role plus the ivay and ivay_test databases. Idempotent. Needs root/sudo.
# Dev-only credentials; they match .env.example and docker-compose.yml defaults.
set -euo pipefail

ROLE="${POSTGRES_USER:-ivay}"
PASS="${POSTGRES_PASSWORD:-ivay_dev}"

if command -v pg_lsclusters >/dev/null && pg_lsclusters -h | grep -q down; then
  pg_ctlcluster "$(pg_lsclusters -h | awk '{print $1}' | head -1)" main start
  sleep 2
fi

as_pg() { if [ "$(id -u)" = 0 ]; then su postgres -c "$*"; else sudo -u postgres bash -c "$*"; fi; }

as_pg "psql -tAc \"SELECT 1 FROM pg_roles WHERE rolname='${ROLE}'\"" | grep -q 1 \
  || as_pg "psql -c \"CREATE ROLE ${ROLE} LOGIN PASSWORD '${PASS}'\""
for db in ivay ivay_test; do
  as_pg "psql -tAc \"SELECT 1 FROM pg_database WHERE datname='${db}'\"" | grep -q 1 \
    || as_pg "createdb -O ${ROLE} ${db}"
done
echo "local postgres ready: ${ROLE}@localhost:5432 (ivay, ivay_test)"
