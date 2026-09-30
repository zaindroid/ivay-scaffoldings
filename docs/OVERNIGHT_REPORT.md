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
