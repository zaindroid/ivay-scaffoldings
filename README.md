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
| `api/` | FastAPI service: event ingest, config, consent ping, order webhook, Alembic migrations |
| `sdk/` | Browser SDK (TypeScript, zero runtime deps, under 10 KB gzipped) and the checkout pixel |
| `demo-store/` | Static product, cart and policy pages served by the `static` container |
| `docker/`, `docker-compose.yml` | Local stack: Postgres 16, API, nginx static server |
| `scripts/` | Dev helpers |

`analysis/` and `e2e/` arrive with their milestones.

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
make test   # API tests (contract tests against contracts/fixtures) and SDK tests
make lint   # ruff + mypy + tsc --noEmit
make size   # build the SDK, fail above 10,240 bytes gzipped
```

`make e2e`, `make simulate` and `make gates` fail with a message until the milestone
that implements them.

## Status

| Milestone | State |
| --------- | ----- |
| M0 Scaffold and contracts | done (see NOTES.md for what could not be verified) |
| M1 SDK foundation, M2 signals, M3 rules, M4 Shopify adapter, M5 backend, M6 merchant audit | done |
| M7 to M8 | in progress (see docs/OVERNIGHT_REPORT.md) |

## Installing the checkout pixel

The pixel records `checkout_started` and order completion so outcomes can be joined to sessions.

1. In Shopify admin open **Settings > Customer events > Add custom pixel** and name it `Ivay`.
2. Paste the contents of [`sdk/pixel/shopify-custom-pixel.js`](sdk/pixel/shopify-custom-pixel.js).
3. Edit the two constants at the top: `IVAY_ENDPOINT` (your Ivay API `/v1/events` URL) and
   `IVAY_SHOP_ID`.
4. Set the pixel's permission to **Analytics** so it only runs for shoppers who consented.
5. Save and connect it. The SDK must be running on the storefront: it writes the session id into the
   cart attribute `ivay_sid`, which the pixel reads. No session id means the pixel sends nothing.

The pixel sends only the event kind, the checkout total and the session id. See NOTES.md (S5, S6)
for what still has to be confirmed on a real shop.

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
