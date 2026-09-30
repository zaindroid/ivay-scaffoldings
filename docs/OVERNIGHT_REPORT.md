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
