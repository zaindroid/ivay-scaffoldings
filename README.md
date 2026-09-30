# Ivay: Phase 0 (shadow mode)

The SDK observes shoppers, computes features, evaluates rules and logs. It renders nothing.
The point is measurement: decide from real pilot data whether Phase 1 is worth building.

- Spec: [`docs/PHASE0_SPEC.md`](docs/PHASE0_SPEC.md)
- Working rules: [`CLAUDE.md`](CLAUDE.md)
- Ambiguities, unverified assumptions, environment changes: [`NOTES.md`](NOTES.md)

## Layout (M0)

| Path | What |
| ---- | ---- |
| `contracts/` | JSON Schemas for the shop config and event envelope, plus shared fixtures |
| `api/` | FastAPI service (currently `/health` only) |
| `demo-store/` | Static pages served by the `static` container (placeholder until M7) |
| `docker/`, `docker-compose.yml` | Local stack: Postgres 16, API, nginx static server |
| `scripts/` | Dev helpers |

`sdk/`, `analysis/` and `e2e/` arrive with their milestones.

## Quick start

With Docker:

```
make install     # virtualenv + API dev dependencies
make up          # postgres :5432, api :8000, static :8080
curl localhost:8000/health
curl localhost:8080/config/shop_dev.json
make down
```

Without Docker (Debian/Ubuntu, needs root or sudo, `postgresql` installed):

```
make install
make local-db    # starts the system Postgres, creates role + ivay/ivay_test databases
make test
```

## Checks

```
make test   # API tests, including the contract tests against contracts/fixtures
make lint   # ruff + mypy
```

`make e2e`, `make size`, `make simulate` and `make gates` fail with a message until the milestone
that implements them.

## Status

| Milestone | State |
| --------- | ----- |
| M0 Scaffold and contracts | done (see NOTES.md for what could not be verified) |
| M1 to M8 | not started |
