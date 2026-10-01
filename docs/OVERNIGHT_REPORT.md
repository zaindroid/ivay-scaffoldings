# Overnight report

Autonomous run, M1 to M8. Each section is appended as its milestone is committed. Push uses
`git -c credential.helper= -c "credential.helper=!gh auth git-credential" push` because the
default credential manager on this machine is denied (403) while the `gh` login has admin.

## M0 fixes (committed 02c9e27)
Nginx config mount, static healthcheck on 127.0.0.1, `ivay_test` DB via initdb, Makefile venv
detection. `make up` was not confirmed under MSYS make; `docker compose up -d --build --wait` works.

## M1: SDK foundation
**Built**: `sdk/` (TypeScript strict, ES2019, Rollup + terser IIFE, vitest + happy-dom): `types.ts`,
`guard.ts`, `consent/{shopify,cookie,custom}.ts`, `identity.ts`, `session-store.ts`, `config.ts`
(validator + fetch), `transport.ts`, `index.ts` wiring. `make size`, `make lint` (adds tsc),
`make test` (adds vitest). The CI `sdk` job could not be pushed (NOTES B1, `docs/ci.pending.yml`).
**Tested**: 54 SDK tests + 8 API tests. Nothing stored or sent before consent; late consent
starts the SDK; failed/invalid/kill-switch config is inert; transport batching (5 s, 20 events,
pagehide, visibilitychange), sendBeacon then fetch keepalive fallback, 60 KB split; SDK
contract test against the shared fixtures. One bug found and fixed while testing: the validator
passed an array index as a length limit (`.every(str)`), which rejected valid configs.
**Bundle**: 2,831 bytes gzipped.
**Blocked**: nothing. Shopify consent API verified from docs (NOTES S1); load timing UNVERIFIED (S2).

## M2: Signals and features
**Built**: `signals/{dwell,scroll,variants,taps,session,registry}.ts`, `features.ts` (100 ms
throttle, leading + trailing), wiring in `index.ts` (page_view, add-to-cart fan-out, collectors).
**Tested**: SDK 83 tests (29 new), API 8. Fake timers and a mocked IntersectionObserver cover
every feature: dwell (50% threshold, out-of-view pause, hidden-tab pause, independent blocks,
1 s re-eval ticker, late blocks, bad selector, no IntersectionObserver), scroll reversals (50 px,
down-to-up only, 30 s decay, passive), variant toggles and reset on add-to-cart, repeated taps
(5 s window, per element, no content kept), session features surviving a simulated navigation
(unit and through `initIvay`), throttling, nothing written before consent.
**Bundle**: 4,343 bytes gzipped.
**Blocked**: nothing. UNVERIFIED: S3 (theme variant change events).

## M3: Rules and decisions
**Built**: `rules.ts` (condition interpreter, engine: eligibility by page type, once per friction
state per session via the session store, priority order, consecutive `fire_seq`, latency sampling),
`decision.ts` (arm assignment, coverage lookup, decision object), `page_summary` on pagehide
(transport `beforePageHide` hook), wiring in `index.ts`.
**Tested**: SDK 113 tests (30 new), API 8. Each starting rule fires and does not fire on noise
(including dwell alone, reversals alone, other page types); no re-fire on 50 repeated ticks, on a
later page, or for a second rule of the same state; fire_seq and priority order; arm stable per
visitor, matches the spec formula, 0 and 10000 bps edges, 10,000-visitor split within 49 to 51%
(seeded, NOTES A37); has_content false when coverage is missing; latency count/p50/max;
end-to-end shipping-policy round trip through `initIvay` (rule fires exactly once, one summary,
every sent batch validates against the envelope schema).
**Bundle**: 5,136 bytes gzipped.
**Blocked**: nothing.

## M4: Shopify adapter and outcomes
**Built**: `platform/shopify.ts` (page type from config URL patterns incl. locale prefix, product id,
country, device, one `/cart.js` request per page, add-to-cart via form submit, cart attribute write
only when different), `pixel/shopify-custom-pixel.js` (checkout_started / checkout_completed to an
`outcome` event, session id from the cart attribute with cookie fallback), `initIvay` platform option
(`"shopify"`, adapter or factory), add-to-cart `outcome` events, `cart_value` into the features,
static demo store pages (`demo-store/products/tee.html`, `cart.html`, both policy pages).
**Tested**: SDK 145 tests (32 new), API 8. Adapter tests run against the demo store markup and assert the
default selectors match it; pixel tests run the real snippet against a fake `analytics`/`browser` and
validate the payload against the envelope schema, including "no session id, nothing sent" and "no
email/address in the payload". Integration: with consent the page view, cart value, cart attribute
write and add-to-cart outcome happen; without consent there is no `/cart.js` request, no write, no cookie.
Bug found and fixed on the way: `stop()` during async start-up did not stop the boot (NOTES A43).
**Bundle**: 5,861 bytes gzipped.
**Blocked**: nothing. Shopify facts: S4 to S6 verified from docs, S7 and S8 UNVERIFIED, list in NOTES.md.

## M5: Backend
**Built**: `alembic/` (migration `0001`: the six tables, indexes, one-order-per-session partial unique
index, the `session_rollup` view), `app/models.py`, `app/schemas.py` (Pydantic contract models),
`app/guards.py` (body limit, JSON parsing for any content type, sliding-window rate limit, Origin and
CORS), `repositories/` (shops, events), `services/` (ingest, config_builder, order_join), routers
(`events`, `consent`, `config`, `webhooks`, `health`), `scripts/seed_dev.py`, Dockerfile runs
migrations on start, compose passes the webhook secret variable.
**Tested**: API 142 tests (134 new), SDK 145. Covers every valid and invalid envelope fixture,
text/plain and JSON and missing content types, malformed and deeply nested bodies, out-of-range
timestamps with rollback, duplicate event and decision ids, unknown shop, wrong, missing and look-alike
origins, per-shop CORS, preflight, 64 KB body limit (declared and streamed), rate limit (per shop,
sliding window, shared unknown-shop bucket), no IP or user agent stored or logged (schema, stored data
and log records), HMAC pass and every failure mode (wrong secret, tampered body, missing, garbage,
empty, secret env outside the prefix), order content extraction and "nothing else stored", webhook and
pixel deduplication in both orders, config serving (contract match, ETag, 304, size limit, invalid
stored config), consent ping (aggregate only), the `session_rollup` view on a four-session fixture,
schema versus `models.py`, Pydantic versus JSON Schema agreement. Mutation check: breaking the HMAC
comparison or the Origin check makes 4 and 5 tests fail respectively.
**Verified against the running stack**: container migrates on start, `curl` config with CORS, text/plain
beacon returns 204, row appears in `session_rollup`.
**Bug found on the way**: Python 3.12 syntax in code for a 3.11 image (caught by mypy, NOTES A58).
**Blocked**: nothing. UNVERIFIED: S9 (webhook payload fields), S10 (pixel Origin), S11 (currency).

## M6: Merchant data audit
**Built**: `app/platforms/base.py` (`MerchantPlatform` protocol, `Coverage`, `ShippingCoverage`),
`shopify.py` (`ShopifyAdminClient` over an injected httpx client with retry on throttling, and
`ShopifyPlatform` with `audit_shipping`, `audit_returns`, `audit_sizing`), `shopware.py` (stub raising
`NotImplementedError`), `replay.py` (fixture-replaying client), sample data, `scripts/audit_merchant_data.py`
(read-only, `--dry`, `--json`, clear refusal without credentials), `make audit-dry`.
**Tested**: API 176 tests (34 new), SDK 145. Shipping rule on a two-profile, paginated fixture (DE made
incomplete by a second profile, CH by an inactive method, FR by a carrier rate, a zero price counts, rest of
world excluded), truncated nested pages reported, empty shop, returns policy in five present/absent shapes,
sizing over pages with blank and null metafields, configurable metafield, read-only guarantee (no `mutation`
or `subscription` anywhere in the queries or the script), protocol conformance, the HTTP client on a mock
transport (URL, token header, JSON body, GraphQL errors, 401/403, 500, non-JSON, network failure, token
never in any error, throttle retry with `Retry-After`, retry limit), the whole platform over the mock
transport, and the script run as a subprocess: dry text and JSON, no credentials, one credential missing.
**Blocked**: nothing. UNVERIFIED: S13 (live query shape), S14 (size charts). Fixtures are written from the
documented schema, not recorded (stated in the fixture and in NOTES S13).

## M7: Demo store, E2E and simulator
**Built**: demo store pages wired to the real bundle (`demo-store/assets/demo.js`, `demo-init.js`, product page
with a spacer for scrolling, cart, both policies), nginx `/sdk/` alias, `e2e/` (Playwright, 7 tests),
`make e2e`, `scripts/simulate_sessions.py` (planted truth), `make simulate`.
**Tested**: E2E 7 of 7 against the live stack (real Chromium, real bundle, real API and Postgres): nothing
exists or is sent before consent; accepting consent starts the SDK without a reload; scroll, size chart,
shipping policy round trip, return, add to cart; a delivery rule fires exactly once (`fire_seq` 1, shadow,
`play` and `propensity` null, `has_content` true), the same session id on every row and in the cart attribute
(written once), `cart_value` 29 in the summaries, four page views, four summaries with latency, the
`session_rollup` row, the raw visitor id absent from every table, the page content unchanged by the SDK;
sizing and returns rules; consent declined and consent ignored produce no cookie, no storage, no request to
the API and zero rows; kill switch and a failing config fetch are inert and the page still works. Mutation
check: making the Shopify consent provider always say yes fails both no-consent tests.
Simulator: 20 API tests (now 196 API tests in total, SDK 145): determinism, no clock, rows validate as
contract events, unique ids, decisions follow the SDK rules, nested funnel, arm formula and per-visitor
stability, trigger rates and coverage within 4 sigma of the closed form, consent rate, holdout share,
latency, the planted signal effect, DB round trip (written rows reproduce the planted truth through
`session_rollup`, idempotent with truncate, a real shop's rows untouched), CLI refuses non-sim shop ids.
Bugs found on the way: a stale `/cart.js` stub made the SDK look like it wrote the cart attribute on every
page (the stub, not the SDK, was wrong: NOTES A67); an asyncpg date type in the simulator's writer; the
platform unit test depending on the live static server (A66).
**Bundle**: 5,861 bytes gzipped.
**Blocked**: nothing. The CI `e2e` job is in `docs/ci.pending.yml` (B1).

## M8: Gate report
**Built**: `analysis/` package (`config.py` and `gates.yaml`, `rollup.py` loader, `auc.py` cross-validated lift,
`gates.py` the eight numbers, `report.py` the report and CLI), `make gates`, `make size` hardened and tested,
analysis added to `make lint`, `make test` and `make install`.
**Tested**: analysis 70 tests (all new). On simulated data the pipeline recovers the planted values: the
empirical truth EXACTLY (addressable share 2,696 of 4,384; fired sessions per state; coverage per state; the
consent rate; max latency) and the planted parameters within 4 standard deviations (trigger rates, coverage,
consent rate, holdout share) or 5 to 12 percent (median latency, proof-test days, sessions per day). The
planted signal effect is recovered: lift +0.067 against an oracle +0.073 (tolerance 0.03), and a control
with every signal effect switched off gives no lift (within 0.015). The report prints all eight numbers
(15 rows, one per friction state where the number is per state) with thresholds, labels simulated output at
the top, on every row and at the end, carries no label on real data, lists every failing and unavailable row,
shows "not available (consent_ping disabled)" instead of a number when there is no ping, and fails the
proof-test row when nothing triggers. Config validation, the AUC on synthetic data (strong signal, no
signal, deliberately leaked columns never used, one-class, determinism, configurable outcome), the CLI
(exit codes, JSON, custom config). SDK: 3 new tests prove `make size` fails above 10,240 bytes gzipped and
counts gzipped, not source, bytes. Mutation checks: dropping the abandoning filter fails a test; letting a
leaky column into the features fails 4.
**Blocked**: nothing. Thresholds are placeholders (NOTES A78).

# Final report (spec section 13)

## What was built, per milestone
- **M0** scaffold, contracts, health, compose, Makefile (plus the fixes found by running it for real).
- **M1** SDK foundation: types, guard, three consent providers, identity, session store, config, transport.
- **M2** signals and features: dwell, scroll reversals, variant toggles, repeated taps, session counters, throttled assembly.
- **M3** rules and decisions: interpreter, once per session per state, priority and `fire_seq`, arms, coverage lookup, latency sampling, page summary.
- **M4** Shopify adapter, checkout pixel, demo store pages.
- **M5** backend: Alembic schema and `session_rollup` view, ingest, config, consent ping, order webhook, hardening.
- **M6** merchant data audit: protocol, Shopify implementation, Shopware stub, read-only script with a dry mode.
- **M7** demo store wired to the real bundle, Playwright E2E, simulator with planted truth.
- **M8** gate report: the eight numbers against provisional thresholds.

## Test results
| Suite | Tests | Result |
| ----- | ----: | ------ |
| API (pytest, real Postgres) | 196 | all pass |
| Analysis (pytest, real Postgres, simulated data) | 70 | all pass |
| SDK (vitest, happy-dom) | 148 | all pass |
| E2E (Playwright, real Chromium, real bundle, API and Postgres) | 7 | all pass |
| **Total** | **421** | **no failures, none skipped** |

`make lint` (ruff, mypy strict, tsc strict for the SDK and E2E) is clean. A fresh `docker compose down -v` then
`up --build --wait` was used for the final run. Mutation checks (deliberately breaking the HMAC comparison, the
Origin check, the consent provider, the abandoning filter and the leakage guard) each made tests fail, so the
tests can fail. Tests that were wrong, not the code, and were changed: the platform unit test depended on the
live static server (A66); an E2E cart stub that did not behave like Shopify was corrected the same session it was written (A67).
Real bugs found by tests and fixed in code: validator index bug (M1), `stop()` during start-up (A43), PEP 695
syntax in a 3.11 image (A58), asyncpg date type (M7).

## SDK bundle size
**5,861 bytes gzipped** by `make size` (limit 10,240). The gate report measures 5,847 with Python's gzip (A84).

## Gate report on simulated data
Produced by `make simulate` then `make gates` (5,000 consented simulated sessions, seed 7, shop `sim_shop`).
It verifies the pipeline only.

```
SIMULATED: pipeline check only.
These numbers verify the pipeline. They say nothing about any shop and are NOT gate results.

Shop: sim_shop   consented sessions: 5000   observed span: 10.0 days

 #  Number                                                                Value  Threshold        Verdict
---------------------------------------------------------------------------------------------------------
 1  Addressable share of abandoning sessions                              61.5%  >= 0.3           pass (simulated)
      2696 of 4384 abandoning sessions touched shipping, returns or size information
 2  Trigger rate: delivery_uncertainty                                    13.8%  >= 0.03          pass (simulated)
      690 fired of 5000 consented sessions
 2  Trigger rate: returns_uncertainty                                      5.8%  >= 0.03          pass (simulated)
      289 fired of 5000 consented sessions
 2  Trigger rate: sizing_uncertainty                                      19.1%  >= 0.03          pass (simulated)
      955 fired of 5000 consented sessions
 3  Grounded-answer coverage: delivery_uncertainty                        76.4%  >= 0.7           pass (simulated)
      527 of 690 fired decisions had content
 3  Grounded-answer coverage: returns_uncertainty                        100.0%  >= 0.7           pass (simulated)
      289 of 289 fired decisions had content
 3  Grounded-answer coverage: sizing_uncertainty                          54.5%  >= 0.7           FAIL (simulated)
      520 of 955 fired decisions had content
 4  Consent rate                                                          62.3%  >= 0.5           pass (simulated)
      9570 consented of 15364 page loads
 5  Signal lift (cross-validated AUC)                                    +0.067  >= 0.02          pass (simulated)
      AUC 0.640 with signals vs 0.573 baseline; 4254 sessions, 1291 positive, 5-fold CV
 6  SDK size (gzipped bytes)                                               5847  <= 10240 (spec)  pass (simulated)
 7  Decision latency p50 (us)                                              45.0  <= 1000          pass (simulated)
 7  Decision latency max (us)                                            1800.9  <= 16000         pass (simulated)
 8  Proof-test duration (days): delivery_uncertainty                       66.7  <= 42            FAIL (simulated)
      2 x 2300 / (500.1 consented sessions per day x trigger rate)
 8  Proof-test duration (days): returns_uncertainty                       159.1  <= 42            FAIL (simulated)
      2 x 2300 / (500.1 consented sessions per day x trigger rate)
 8  Proof-test duration (days): sizing_uncertainty                         48.2  <= 42            FAIL (simulated)
      2 x 2300 / (500.1 consented sessions per day x trigger rate)

11 of 15 rows pass, 4 fail, 0 not available.
  FAILING: 3 Grounded-answer coverage: sizing_uncertainty
  FAILING: 8 Proof-test duration (days): delivery_uncertainty
  FAILING: 8 Proof-test duration (days): returns_uncertainty
  FAILING: 8 Proof-test duration (days): sizing_uncertainty
Thresholds are PROVISIONAL (proposed by Claude) except the SDK size limit, which the spec fixes: addressable_share, consent_rate, decision_latency_max_us, decision_latency_p50_us, grounded_coverage, proof_test_days, signal_lift_auc, trigger_rate

SIMULATED: pipeline check only. Do not read these verdicts as gate results.
```

The failures shown are expected consequences of the planted parameters and the provisional thresholds (the
planted sizing coverage is 55%, the planted returns trigger rate 6%), not findings about any shop.

## UNVERIFIED: what a pilot shop must confirm (details in NOTES.md)
| Id | Assumption | What to check on a real shop |
| -- | ---------- | ---------------------------- |
| S2 | Shopify's Customer Privacy API is loaded when the SDK runs, and `analyticsProcessingAllowed()` is right in regions without a banner | `Shopify.customerPrivacy` exists at SDK start, or the SDK never starts; its value before any choice |
| S3 | Theme variant inputs fire a bubbling `change` event | `variant_toggles_since_atc` rises when a size is picked |
| S5 | The cart attribute `ivay_sid` reaches the order, and who can see it | Admin order shows it; check checkout, order status page and emails for shoppers |
| S6 | Pixel can read the storefront cookie; third-party `fetch` from the sandbox is allowed; permission "Analytics" follows consent | Place a test order and look for the outcome row; one doc page for the sandbox returned 404 |
| S7 | `ShopifyAnalytics.meta.product.id`, `Shopify.country`, `Shopify.routes.root` exist on live pages (undocumented) | Read them on a product page; product id matches the Admin id the audit uses |
| S8 | Add-to-cart is detected from the form `submit` (the spec's "theme cart events" are not implemented: none documented) | Add to cart on the pilot theme and look for the outcome |
| S9 | Order webhook body carries `note_attributes` with `ivay_sid` and `total_price`; 204 is accepted | Capture a real `orders/paid` body |
| S10 | The `Origin` of pixel requests | A 403 on `/v1/events` from checkout means the origin must be added to `allowed_origins` |
| S11 | Pixel value (presentment currency) and webhook value (shop currency) differ | Do not compare order values across currencies |
| S13 | The Admin GraphQL audit query shape and scopes (`read_shipping`, `read_legal_policies`, `read_products`), API version `2025-01`; fixtures are written from the documented schema, not recorded | Run `audit_merchant_data.py` live; fix the query on the first GraphQL error |
| S14 | Where size charts live | Ask the merchant; only a metafield (`custom.size_chart`) is measured |
| S1, S4, S12 | Verified against shopify.dev (consent API, `/cart.js` units, field names) | Zero-decimal currencies (S4) still need a look |

## Provisional thresholds (proposed by Claude, `analysis/gates.yaml`)
| Number | Threshold | Reason |
| ------ | --------- | ------ |
| 1 Addressable share | >= 30% | below this little is left for an on-page answer to address |
| 2 Trigger rate (per state) | >= 3% | rarer states make the proof test very long |
| 3 Grounded coverage (per state) | >= 70% | most detected moments need an answer |
| 4 Consent rate | >= 50% | smaller audiences are small and possibly unrepresentative |
| 5 Signal lift (CV AUC) | >= +0.02 | two AUC points is small but clearly non-zero |
| 6 SDK size | <= 10,240 bytes | fixed by the spec, not provisional |
| 7 Decision latency | p50 <= 1,000 us, max <= 16,000 us | well under a millisecond; never a frame |
| 8 Proof-test duration (per state) | <= 42 days; n = 2,300 per arm (spec default) | longer than six weeks is too slow for a pilot |

## Open questions for the owner (from NOTES.md)
1. A12: confirm or replace every threshold above except the size limit.
2. `required_consent`: accept only Shopify's consent categories, or any string (M0 accepts any non-empty string).
3. S14: where does the pilot shop keep size charts?
4. S9, S10, S5: capture a real order webhook, the pixel's `Origin`, and check what shoppers can see of the cart attribute.
5. A47: the rate limit is per process; decide before running more than one API worker.
6. B1: grant the GitHub token the `workflow` scope or apply `docs/ci.pending.yml` by hand.

## Known issues and environment notes
- **CI could not be updated.** The GitHub token has no `workflow` scope, so `.github/workflows/ci.yml` still has only the M0 jobs. The full intended workflow (api, sdk, analysis, compose, e2e) is `docs/ci.pending.yml` (NOTES B1).
- `make up` does not run under MSYS make on this Windows machine (docker compose plugin lookup); `docker compose up -d --build --wait` does. Port 8000 is held by another project's container, so everything was verified with `API_PORT=8001`. No container, volume or network outside this repo was touched.
- Two Windows-only traps hit and fixed: the default git credential was denied (pushes used `gh auth git-credential`), and Python's default text encoding on Windows corrupted section signs in NOTES.md for a few commits (repaired in the M5 commit; scripts now write UTF-8).
- Line endings: the working copy is LF; git warns about CRLF conversion on this machine. No functional effect found.
- The simulator's fire order within a session is random (A71), and `make e2e` truncates the dev database's event tables (A69).

## How to run everything
```
make install PYTHON=<python 3.11+>          # venv, API and analysis packages
API_PORT=8001 docker compose up -d --build --wait
make lint && make test && make size
make e2e API_PORT=8001
make simulate && make gates                  # SIMULATED data, pipeline check only
make audit-dry                               # merchant data audit on sample data
```
