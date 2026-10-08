#!/bin/sh
# Deploy the hosted pilot to the VPS in ONE ssh connection (fail2ban blocks repeated ones).
# Usage: deploy/pilot/deploy.sh      (run from the repo root; needs the ssh key from CLAUDE.md)
set -eu
HOST="${VPS:-root@2.25.105.110}"
KEY="${VPS_KEY:-$HOME/.ssh/hostinger_vps_ed25519}"

(cd sdk && npm run build --silent)
tar czf - --exclude='__pycache__' --exclude='.venv' --exclude='node_modules' --exclude='*.pyc' \
  api contracts demo-store sdk/dist scripts/seed_dev.py deploy/pilot \
| ssh -i "$KEY" -o StrictHostKeyChecking=no "$HOST" \
  "mkdir -p /opt/ivay-pilot && tar xzf - -C /opt/ivay-pilot && sh /opt/ivay-pilot/deploy/pilot/remote.sh"
