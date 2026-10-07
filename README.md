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
| `analysis/` | Gate report: loads `session_rollup`, computes the eight numbers, prints them against `gates.yaml` |
| `sdk/` | Browser SDK (TypeScript, zero runtime deps, under 10 KB gzipped) and the checkout pixel |
| `demo-store/` | Static product, cart and policy pages served by the `static` container, wired to the real SDK bundle |
| `e2e/` | Playwright tests: the real bundle in Chromium against the demo store, the API and Postgres |
| `docker/`, `docker-compose.yml` | Local stack: Postgres 16, API, nginx static server |
| `scripts/` | Dev helpers |



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
make e2e    # Playwright against the running stack (start it first, see below)
make simulate  # SIMULATED sessions with planted truth into the dev database
make gates     # the gate report (default: the simulated shop; SHOP=my_shop for real data)
```



## Status

| Milestone | State |
| --------- | ----- |
| M0 Scaffold and contracts | done (see NOTES.md for what could not be verified) |
| M1 SDK foundation, M2 signals, M3 rules, M4 Shopify adapter, M5 backend, M6 merchant audit, M7 demo store, E2E and simulator, M8 gate report | done |
| Pilot | not started: see the UNVERIFIED list in NOTES.md and docs/OVERNIGHT_REPORT.md |

## Demo pilot with live data

```
API_PORT=8001 docker compose up -d --build --wait   # use 8001 if 8000 is taken
DATABASE_URL=postgresql+asyncpg://ivay:ivay_dev@127.0.0.1:5432/ivay API_PORT=8001 python scripts/seed_dev.py
make live                                           # in a second terminal: follows shop_dev
```

Open `http://localhost:8080/products/tee.html?api=http://localhost:8001` (the `api` value is
remembered), click Accept on the demo banner, then scroll, open the size guide, add to cart and
visit the cart. Each page view, rule decision, evaluation summary and outcome appears in
`make live` as it lands. Nothing is recorded before Accept.

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
