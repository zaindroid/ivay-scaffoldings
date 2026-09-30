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

## Resuming on another machine

The work lives on branch `claude/inspiring-mccarthy-mnruk6` (nothing is merged to the default
branch yet).

```
git clone https://github.com/zaindroid/ivay-scaffoldings.git
cd ivay-scaffoldings
git checkout claude/inspiring-mccarthy-mnruk6
make install
make up            # Docker available: postgres + api + static server
curl localhost:8000/health && curl localhost:8080/config/shop_dev.json
make test && make lint
```

`make up` has never been run (the build sandbox had no Docker daemon), so run it first and fix
anything it turns up before starting M1. If Docker is not available on your machine either, use
`make local-db` as described above.

Next step: M1 (SDK foundation), spec section 10. Read `CLAUDE.md` and `NOTES.md` first; open
questions for you are at the bottom of `NOTES.md`.
