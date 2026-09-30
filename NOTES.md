# NOTES

Working log for Phase 0. Every ambiguity and every unverified Shopify assumption goes here
(see `CLAUDE.md`). Spec: `docs/PHASE0_SPEC.md`.

## Environment changes

- **M0 verified with a real Docker daemon** (Docker Desktop 29.6.2, Compose v5.3.1, Windows 11).
  Earlier sandbox notes (no daemon, Postgres via apt) are superseded; `scripts/local_db.sh`
  remains for Docker-free Linux use. Fixes found by actually running `docker compose up`:
  1. **nginx config mount failed** (`read-only file system`): the fixture was bind-mounted at
     `/usr/share/nginx/html/config/shop_dev.json`, inside the read-only `demo-store` mount where
     `config/` does not exist. Now mounted at `/usr/share/nginx/config/shop_dev.json` and served
     by `alias` in `docker/nginx.conf`.
  2. **`static` healthcheck always unhealthy**: `localhost` resolves to `::1` in alpine and nginx
     listens on IPv4 only. Healthcheck now uses `127.0.0.1`.
  3. **`ivay_test` database missing** under compose (only `local_db.sh` created it), so
     `test_health_ok_with_real_database` returned 503. Added `docker/initdb/01-test-db.sql`,
     mounted into `/docker-entrypoint-initdb.d`. It only runs on a fresh volume; on an existing
     one run `docker compose down -v` or `CREATE DATABASE ivay_test OWNER ivay;` by hand.
  4. **Makefile hard-coded `.venv/bin/`**; Windows venvs use `Scripts/`. Now detected; `make install`
     accepts `PYTHON=/path/to/python` (MSYS `python3` is MinGW and cannot build pydantic-core).
- Local-machine notes (not repo bugs): another project's container (`lifeline-api`) holds host port
  8000, so verification ran with `API_PORT=8001`. Under MSYS `make`, `make up` fails with
  "unknown shorthand flag: 'd'" because MSYS sets `HOME=/home/<user>` and docker cannot find its
  compose plugin; `DOCKER_CONFIG` and `HOME` overrides did not fix it, and a standalone
  `docker-compose` fallback behaved inconsistently (port env not honoured). `make up` is not
  confirmed under MSYS make; the identical `docker compose up -d --build --wait` was run directly
  and passes. `make install`, `make lint` and `make test` do run through MSYS make.
  Not yet verified: `make up` from a native `make` (Linux/CI). The CI `compose` job covers that.
- Postgres here is 16.13 (spec asks for 15+).

## Ambiguities and the interpretation chosen

| # | Where | Question | Interpretation |
| - | ----- | -------- | -------------- |
| A1 | §6 | Layout shows an `ivay/` root. | Repo root is the `ivay/` root. No subfolder. |
| A2 | §6 | M0 says "repo layout", but git does not track empty directories. | Only directories with content exist (`contracts`, `api`, `demo-store`, `docker`, `scripts`). `sdk`, `analysis`, `e2e` appear in the milestone that fills them. |
| A3 | §7.2 vs §8.9 | Envelope shows `visitor_hash` and `page_id` as required, but the checkout pixel only knows `ivay_sid` and has no page. | Both are optional in the schema, and required (schema `if/then`) whenever the batch contains a `page_view`, `rule_fired` or `page_summary`. Pixel batches carry only `outcome` events. Fixtures `valid/event-envelope.pixel-outcome.json` and `invalid/event-envelope.sdk-events-without-*` cover both sides. |
| A4 | §8.1 | "If ... mode is unknown, stop." Schema validation also rejects unknown modes. | Schema enum is `shadow`/`live`. An unknown mode fails validation, so the SDK is inert either way. The SDK test in M1 asserts the behaviour, not which check caught it. |
| A5 | §7.1 | Priorities for the returns and sizing rules are not given. | delivery=1, returns=2, sizing=3, in `fixtures/valid/shop-config.full.json`. |
| A6 | §7.1 | Config is strict (`additionalProperties: false`) or open? | Strict, on every object, so the contract test catches drift. A new field means a `schema_version` bump. |
| A7 | §7.1 | Which feature names may appear in a rule leaf? | Any `^[a-z][a-z0-9_]*$`. Restricting to a list would force a schema change each time a signal is added, against §4. The SDK ignores rules whose feature it does not know (decided in M3; will be recorded here). |
| A8 | §7.2 | Event/ID formats. | IDs: `^[A-Za-z0-9_-]{8,64}$`. `ts` and `sent_at`: integer ms since epoch. `country`: ISO-3166 alpha-2 uppercase or null. `features` values: scalar or null only (no nesting), which also enforces "count events, do not record content". |
| A9 | §7.2 | Schema draft. | JSON Schema 2020-12 (needed for `contains` in A3). |
| A10 | §9.2 | `/health` content. | Returns `{"status":"ok","db":"ok"}` after `SELECT 1`; 503 `degraded` if the DB is unreachable, with no error detail in the body. |
| A11 | §9.3 | Access logs. | Container runs uvicorn with `--no-access-log` (the default log line contains client IP). Rest of the hardening is M5. |
| A12 | §2 | **Gate thresholds are not given anywhere** ("provisional", in `analysis/gates.yaml`). | Needed by M8. I will propose values there, flag them as my placeholders, and ask you to confirm. |
| A13 | §2 #4 | Consent rate needs the anonymous ping, which is off by default. | The report will print "not available (consent_ping disabled)" instead of a number when there is no ping data. |
| A14 | §4 | Spec wants a contract test "on each side". SDK side does not exist yet; Pydantic models arrive in M5. | M0 has the schema-level test in `api/tests/test_contracts.py`. The SDK-side test is added in M1, the Pydantic-vs-fixtures test in M5. Both read the same fixtures and `manifest.json`. |
| A15 | §7.1 | Config size limit (50 KB). | Not applicable yet. Recorded when the builder exists (M5). |
| A16 | §5 | Dev DB credentials in compose and `.env.example`. | Dev-only defaults (`ivay` / `ivay_dev`), Postgres port bound to 127.0.0.1. Not secrets; nothing production-facing uses them. |

## Contract fixtures

`contracts/fixtures/manifest.json` maps each invalid fixture to the JSON pointer where its
validation error must appear, so a fixture cannot start failing for an unrelated reason. The API
test also checks that the manifest and the directory list the same files.

## Unverified Shopify assumptions

None yet. Nothing in M0 touches Shopify. The list starts in M1 (Customer Privacy API) and M4
(storefront globals, `/cart.js`, cart attributes, custom pixel API). Each entry will say what to
check on a real shop.

## Open questions for the owner

1. A12: confirm or replace the gate thresholds when M8 proposes them.
2. Should `required_consent` accept only Shopify's consent categories, or any string? M0 accepts
   any non-empty string; revisit after M1 verifies the Shopify API.
