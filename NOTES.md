# NOTES

Working log for Phase 0. Every ambiguity and every unverified Shopify assumption goes here
(see `CLAUDE.md`). Spec: `docs/PHASE0_SPEC.md`.

## Environment changes

- **Docker daemon is not available in the build sandbox** (`docker` CLI and Compose v5.1 are
  installed, `docker info` fails). Per the task note: Postgres 16.13 was installed with apt and
  runs directly; `scripts/local_db.sh` (`make local-db`) creates the `ivay` role and the `ivay` /
  `ivay_test` databases. `docker-compose.yml` is kept for local use.
  - Consequence: **`make up` was never run here.** What was verified instead: `docker compose
    config -q` parses the file; the API was installed non-editable into a clean venv (what the
    Dockerfile does) and served `/health` against the local Postgres; the static files were served
    with `python -m http.server` from a directory laid out like the nginx mounts. Not verified: the
    image build, the nginx config, and the compose healthchecks. The CI `compose` job runs the real
    `make up` equivalent and is the first place that will show a problem.
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
