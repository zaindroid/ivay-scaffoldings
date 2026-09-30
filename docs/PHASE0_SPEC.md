# Ivay Phase 0: Shadow-Mode Build Spec

You are building Phase 0 of Ivay. Read this whole file before writing code.
Work one milestone at a time, in order. After each milestone, run its
"done when" checks, then stop and report: what was built, what was tested,
what is blocked. Do not start the next milestone until told to.

## 1. What this is and why

Ivay detects a shopper who is stuck on an unanswered question (delivery,
returns, sizing), answers it on the page from the merchant's own data, and
proves the effect against a holdout.

Phase 0 is shadow mode. The SDK observes, computes features, evaluates rules
and logs. It never renders anything and never changes the page. The purpose
is measurement: decide with real pilot data whether Phase 1 is worth building.

That purpose drives three design requirements that are easy to miss:

1. We must log every consented session, not only sessions where a rule fired.
   The gate numbers need denominators and non-triggered sessions.
2. We must capture outcomes (add-to-cart, checkout started, order completed)
   for every session, and join them to the session.
3. Storefronts are multi-page. Session state must survive page navigation.

## 2. The numbers Phase 0 must be able to compute

The gate report (Milestone 8) computes these from the database:

| # | Number | Definition |
| - | ------ | ---------- |
| 1 | Addressable share | Of abandoning sessions, the share that touched shipping, returns or size info |
| 2 | Trigger rate | Per friction state: sessions where the rule fired / consented sessions |
| 3 | Grounded-answer coverage | Per friction state: fired decisions with content available / fired decisions |
| 4 | Consent rate | Consented page loads / all page loads (from the anonymous ping, if enabled) |
| 5 | Signal lift | Cross-validated AUC of (baseline + signals) minus AUC of baseline (page type, device, cart value), predicting the outcome |
| 6 | SDK size | Gzipped bytes of the production bundle |
| 7 | Decision latency | p50 and max of rule-evaluation time, measured in the field by the SDK |
| 8 | Proof-test duration | days = 2n / (sessions_per_day x consent_rate x trigger_rate) |

Definitions to implement exactly:

- Abandoning session: viewed at least one product or cart page and has no
  order_completed outcome.
- Outcome for the AUC model: configurable; default is add_to_cart for
  product-page sessions.
- n for number 8 comes from `analysis/gates.yaml` (default 2300).

Thresholds live in `analysis/gates.yaml` and are provisional. The report
prints each number next to its threshold and never hides a failing one.

Numbers computed from simulated data only verify the pipeline. Label them
"SIMULATED: pipeline check only" in every report. Never present them as
gate results.

## 3. Architecture

```
Browser (SDK)                          Server
consent -> identity -> config          POST /v1/events   (batched beacons)
signals -> features -> rules           POST /v1/consent-ping (optional)
decisions + page summaries ----------> POST /v1/webhooks/shopify/orders
outcomes (add-to-cart) --------------> GET  /v1/config/{shop_id}
checkout pixel snippet --------------> analysis/ (gate report, offline)
```

Constraints, with reasons:

- Decisions run in the browser with no network round trip, so latency does
  not depend on the network.
- The server only serves config and receives logs. No WebSocket, no SSE.
- Nothing is stored on the device and no identifier is created before
  consent. German law requires consent for this kind of access.
- Never capture form values, keystrokes, element text, email, address or
  payment fields. Count events; do not record content.
- The SDK must never break the host page. Every entry point is wrapped in
  try/catch, and the SDK disables itself after 5 caught errors.
- The core bundle stays at or under 10 KB gzipped, with zero runtime
  dependencies.

## 4. Modularity rules

The codebase will be extended with new signals, new platforms (Shopware),
live interventions (Phase 1) and a learning layer. Build for that:

- One versioned contract. `contracts/` holds JSON Schemas for the shop
  config and the event envelope, plus example fixtures. SDK types and API
  Pydantic models both conform to it, and a contract test on each side
  validates the shared fixtures.
- SDK modules talk through small interfaces defined in `types.ts`:
  `ConsentProvider`, `PlatformAdapter`, `SignalCollector`, `Transport`.
  Adding a signal means adding one file and registering it. Interfaces are
  types only, so they cost no bytes.
- Rules are data. The rule engine interprets conditions from the config;
  thresholds change without a code deploy.
- The API is split into routers (HTTP), services (logic) and repositories
  (SQL). Merchant platforms sit behind a `MerchantPlatform` protocol.
- A `mode` field in the config ("shadow" or "live") already exists so
  Phase 1 adds a renderer without restructuring. Only "shadow" is
  implemented now.

Do not add abstraction beyond this. Prefer plain functions.

## 5. Tech stack

- SDK: TypeScript (strict), ES2019 output, Rollup + terser, IIFE bundle.
  Tests: vitest with happy-dom and fake timers.
- API: Python 3.11+, FastAPI, SQLAlchemy 2 (async) + asyncpg, Alembic,
  Pydantic v2. Tests: pytest against a real Postgres (JSONB is used).
- Analysis: separate Python package (pandas, scikit-learn) so the API
  image stays small.
- DB: PostgreSQL 15+.
- E2E: Playwright against a static demo store.
- Dev: Docker Compose. Lint: ruff + mypy for Python, tsc --noEmit for TS.
- A Makefile with: `make up`, `make test`, `make e2e`, `make size`,
  `make simulate`, `make gates`.

## 6. Repository layout

```
ivay/
  README.md  NOTES.md  Makefile  docker-compose.yml  .env.example
  docs/PHASE0_SPEC.md
  contracts/
    shop-config.schema.json
    event-envelope.schema.json
    fixtures/            # valid and invalid examples, used by both sides
  sdk/
    package.json  tsconfig.json  rollup.config.js
    src/
      index.ts           # initIvay, wiring only
      types.ts           # interfaces and shared types
      consent/           # shopify.ts, cookie.ts, custom.ts
      platform/          # shopify.ts (page context, cart, add-to-cart)
      identity.ts        # visitor hash, session id
      session-store.ts   # session-scoped state in sessionStorage
      config.ts          # fetch, validate, cache
      signals/           # one file per collector + registry.ts
      features.ts        # assembles Features from collectors + store
      rules.ts           # condition interpreter
      decision.ts        # arm assignment, content lookup, decision object
      transport.ts       # batching, sendBeacon, fetch keepalive fallback
      guard.ts           # try/catch wrapper, error budget, self-disable
    tests/
    pixel/shopify-custom-pixel.js   # checkout outcomes snippet
  api/
    pyproject.toml  alembic.ini  alembic/
    app/
      main.py
      routers/           # events.py, config.py, consent.py, webhooks.py, health.py
      services/          # ingest.py, config_builder.py, order_join.py
      repositories/
      platforms/         # base.py (protocol), shopify.py, shopware.py (stub)
      models.py  schemas.py  db.py  settings.py
    tests/
  analysis/
    pyproject.toml  gates.yaml
    ivay_analysis/       # rollup.py, gates.py, auc.py, report.py
    tests/
  demo-store/            # static product, cart, policy pages for E2E
  e2e/                   # Playwright tests
  scripts/
    seed_dev.py  simulate_sessions.py  audit_merchant_data.py
```

## 7. Contracts

### 7.1 Shop config

```json
{
  "schema_version": "1.0",
  "shop_id": "shop_dev",
  "mode": "shadow",
  "kill_switch": false,
  "holdout_bps": 5000,
  "holdout_salt": "fixed-public-string",
  "log_endpoint": "http://localhost:8000/v1/events",
  "required_consent": ["analytics"],
  "consent_ping": false,
  "selectors": {
    "shipping_block": "[data-ivay-block='shipping']",
    "returns_block": "[data-ivay-block='returns']",
    "size_block": "[data-ivay-block='size']",
    "size_chart_trigger": "[data-ivay='size-chart'], a[href*='size-guide']",
    "variant_selector": "form[action*='/cart/add'] [name='id'], variant-selects input",
    "add_to_cart_form": "form[action*='/cart/add']"
  },
  "url_patterns": {
    "product": "^/products/",
    "cart": "^/cart",
    "shipping_policy": "^/policies/shipping-policy",
    "returns_policy": "^/policies/refund-policy"
  },
  "rules": [
    {
      "id": "delivery_v1", "version": "r1", "priority": 1,
      "friction_state": "delivery_uncertainty",
      "pages": ["product", "cart"],
      "when": { "any": [
        { "f": "shipping_page_visited", "op": "eq", "v": true },
        { "all": [
          { "f": "shipping_block_dwell_s", "op": "gte", "v": 40 },
          { "f": "scroll_reversals_30s", "op": "gte", "v": 2 }
        ]}
      ]}
    }
  ],
  "plays": { "delivery_uncertainty": ["direct_answer", "direct_answer_plus_reassurance"] },
  "content": {
    "delivery_uncertainty": { "by_country": { "DE": "shipping_eta:DE" } },
    "returns_uncertainty": { "shop": "returns_policy:v1" },
    "sizing_uncertainty": { "product_ids": ["4821"] }
  }
}
```

Notes:

- Selectors and URL patterns are per shop because merchant themes differ.
  The Shopify adapter supplies defaults; the config overrides them.
- `holdout_salt` is public by necessity. It is not a secret.
- The `content` block is a compact coverage index, not the answers
  themselves. If a built config exceeds 50 KB, record it in NOTES.md.
- Add the returns and sizing rules in the same format:
  returns: `returns_page_visited eq true` on product or cart pages;
  sizing: `size_chart_opens gte 2` or `variant_toggles_since_atc gte 3`
  on product pages.
- If the config fetch fails or validation fails, the SDK does nothing.
  There is no default rule set.

### 7.2 Event envelope

One POST carries a batch:

```json
{
  "schema_version": "1.0",
  "shop_id": "shop_dev",
  "visitor_hash": "sha256-hex",
  "session_id": "random-id",
  "page_id": "random-id",
  "sent_at": 1790000000000,
  "events": [ { "type": "page_view", "event_id": "...", "ts": 0 } ]
}
```

Event types:

- `page_view`: page_type, device, product_id (nullable), country (nullable).
- `rule_fired`: decision_id, friction_state, rule_id, rule_version,
  fire_seq, arm, mode, play, propensity, content_ref, has_content,
  features (snapshot at fire time).
- `page_summary`: final features snapshot for the page, plus
  eval_count, eval_p50_us, eval_max_us. Sent on pagehide.
- `outcome`: kind (add_to_cart, checkout_started, order_completed),
  value (nullable), source (sdk, pixel, webhook).

Every event has a unique `event_id` so ingestion is idempotent; beacons
can arrive twice.

## 8. SDK behaviour

### 8.1 Start-up sequence

`initIvay({ shopId, configBase, consent, platform })`

1. Resolve the consent provider from the init options (not from the remote
   config, which is not fetched yet).
2. If consent is not granted: create nothing, store nothing. Subscribe to
   consent changes and continue from step 3 if consent arrives later.
   If `consent_ping` must be honoured, see 8.8.
3. Fetch the config. Validate it. If `kill_switch` is true or mode is
   unknown, stop.
4. Create or read visitor and session identity.
5. Emit `page_view`. Start signal collectors. Evaluate rules on each
   feature update. Emit `page_summary` on pagehide.

### 8.2 Consent providers

Interface: `{ isGranted(purposes): boolean; onChange(cb): void }`.

- `shopify`: uses Shopify's Customer Privacy API. Verify the exact calls
  and the consent-change event against the current Shopify documentation
  before implementing. If you cannot verify, mark it UNVERIFIED in NOTES.md.
- `cookie`: `{ name, grantedPattern }` for shops with another consent tool.
- `custom`: a function supplied by the integrator.

### 8.3 Identity and session

- Visitor: first-party cookie `ivay_vid`, 16 random bytes hex, 1 year,
  SameSite=Lax, Secure. Visitor hash = SHA-256 hex of (value + holdout_salt)
  using `crypto.subtle`, which is async. The raw value is never sent.
- Session: first-party session cookie `ivay_sid` (the checkout pixel must
  be able to read it), random id, 30 minutes of inactivity ends the session.
- Session store: session-scoped state in sessionStorage under one key.
  It holds session-scoped features, which friction states have already
  fired, and `fire_seq`.
- None of this exists before consent.

### 8.4 Signals

Each collector implements
`{ id; start(ctx): void; snapshot(): Partial<Features>; stop(): void }`.
All listeners are passive. Feature updates are throttled to one per 100 ms.

Page-scoped features:

- `shipping_block_dwell_s`, `returns_block_dwell_s`, `size_block_dwell_s`:
  seconds the block is at least 50% in view while the tab is visible.
- `scroll_reversals_30s`: direction changes from down to up of at least
  50 px, in the last 30 s.
- `variant_toggles_since_atc`: variant changes since the last add-to-cart.
- `repeated_taps_5s`: max taps on one element in 5 s. Track elements in a
  WeakMap; do not store selectors or text.

Session-scoped features (kept in the session store):

- `shipping_page_visited`, `returns_page_visited`
- `size_chart_opens`, `tab_hidden_count`, `pages_viewed`
- `cart_adds`

Context: `page_type`, `device` (from viewport width and pointer type),
`cart_value`, `product_id`, `country`. These come from the platform adapter.

### 8.5 Platform adapter

Interface: `getPageContext()`, `getCart()`, `onAddToCart(cb)`,
`setCartAttribute(key, value)`.

Shopify implementation:

- Page type from URL patterns. Product id and country from the storefront
  globals Shopify exposes; verify which ones against current docs.
- Cart value from one same-origin request to `/cart.js` per page load.
- Add-to-cart detected by submit on the add-to-cart form and by the theme's
  cart events where available. Do not monkey-patch `fetch` or XHR.
- After consent, write the session id into a cart attribute so it arrives
  on the order. Verify the attribute mechanism and its visibility to the
  merchant and shopper against current docs; record findings in NOTES.md.

### 8.6 Rules

- Conditions: `all`, `any`, and leaves `{ f, op, v }` with ops
  eq, gte, lte, gt, lt.
- A rule is eligible only on its listed page types.
- Each friction state fires at most once per session. The session store
  records it. Without this, a rule would log on every tick.
- Evaluate every eligible rule on every update. If several fire in the same
  tick, order them by `priority`. Each firing gets the next `fire_seq`.
  The first-fired state is therefore the chronologically first one.
- Wrap evaluation in `performance.now()` and keep count, p50 and max for
  the page summary.

### 8.7 Decisions

- `arm`: first 8 hex chars of SHA-256(visitor_hash + holdout_salt) as an
  integer, modulo 10000. Below `holdout_bps` is "holdout", else "treatment".
  It is logged in shadow mode to verify the split is stable and even.
- In shadow mode `play` and `propensity` are null. In live mode (not built
  now) play is uniform over the configured plays and
  propensity = 1 / number of plays. Never hard-code 0.5.
- `content_ref` and `has_content` come from the config's coverage index,
  using friction state, product id and country.
- `decision_id` and other ids: random from `crypto.getRandomValues`.
  No id library.

### 8.8 Transport

- Buffer events; flush every 5 s, at 20 events, and on `pagehide` and on
  `visibilitychange` to hidden. Do not use `unload` or `beforeunload`.
- Send with `navigator.sendBeacon(url, string)`. That arrives as
  `text/plain`, so the API must parse the raw body as JSON whatever the
  content type. If sendBeacon is missing or returns false, fall back to
  `fetch` with `keepalive: true`.
- Keep each batch under 60 KB.
- Consent ping: only if `consent_ping` is enabled at init. One request per
  page load with `{ shop_id, consented }` and nothing else. No identifiers,
  no storage. It is off by default because it needs legal review.

### 8.9 Checkout pixel snippet

`sdk/pixel/shopify-custom-pixel.js` is a Shopify custom pixel the merchant
pastes into Settings > Customer events. It subscribes to the checkout
started and checkout completed standard events, reads `ivay_sid`, and posts
an `outcome` event. Verify the pixel API for subscribing and for reading
cookies against current docs. Document the install steps in README.md.

## 9. Backend

### 9.1 Tables (Alembic is the only source of schema)

- `shop`: shop_id PK, platform, allowed_origins (text[]), config (jsonb),
  webhook_secret_ref.
- `page_view`: event_id PK, shop_id, visitor_hash, session_id, page_id,
  ts, received_at, page_type, device, product_id, country.
- `decision_log`: decision_id PK, event_id unique, shop_id, visitor_hash,
  session_id, page_id, ts, received_at, friction_state, rule_id,
  rule_version, fire_seq, arm, mode, play, propensity, content_ref,
  has_content, features (jsonb).
- `page_summary`: event_id PK, shop_id, session_id, page_id, ts,
  features (jsonb), eval_count, eval_p50_us, eval_max_us.
- `outcome_event`: event_id PK, shop_id, session_id, kind, value, source,
  ts, received_at.
- `consent_ping_daily`: (shop_id, day, consented) PK, count. Aggregated
  counter only; no per-request rows.
- View `session_rollup`: one row per session with final session-scoped
  features, max of page-scoped features, page counts, first-fired friction
  state, and outcome flags. The gate report reads this view.

Index shop_id, session_id and ts on the event tables.

### 9.2 Endpoints

- `POST /v1/events`: parse raw body as JSON, validate against the envelope
  schema, route events to tables. Insert with ON CONFLICT DO NOTHING.
  Return 204. Invalid payload returns 422.
- `POST /v1/consent-ping`: increments the daily counter. 204.
- `GET /v1/config/{shop_id}`: returns the built config with cache headers.
  In dev the same JSON is also served as a static file.
- `POST /v1/webhooks/shopify/orders`: verify the HMAC signature with the
  shop's secret, extract order value and the session-id attribute, write an
  `order_completed` outcome with source "webhook". Store nothing else from
  the order payload. Deduplicate against the pixel's outcome by session.
- `GET /health`.

### 9.3 Ingest hardening

These endpoints are public and unauthenticated, so:

- Reject unknown shop_id. Check the Origin header against
  `allowed_origins`. Set CORS per shop, not `*`.
- Body size limit 64 KB. Basic rate limit per shop.
- Do not store IP addresses or user agents, and keep them out of app logs.
- Record `received_at` server-side; never trust client time alone.

### 9.4 Merchant platforms

`platforms/base.py` defines the protocol:
`audit_shipping()`, `audit_returns()`, `audit_sizing()`, each returning
counts of covered and total items. `shopify.py` implements it against the
Admin GraphQL API with an injected HTTP client; tests use recorded
fixtures. `shopware.py` is a stub raising NotImplementedError.

`scripts/audit_merchant_data.py` prints coverage per friction state:
share of shipping countries with complete rates, whether a return policy
exists, share of products with a size chart. It is read-only. A live run
needs credentials from the environment; without them it exits with a
clear message.

Verify Admin API fields against current docs. Do not guess field names.

## 10. Milestones

Each milestone ends with its checks passing and a short report.

**M0: Scaffold and contracts.** Repo layout, Docker Compose (postgres,
api, static server for config and demo store), Makefile, CI workflow,
JSON Schemas and fixtures, NOTES.md.
Done when: `make up` starts all services, `/health` returns ok, fixtures
validate against the schemas in a test.

**M1: SDK foundation.** types, guard, consent providers, identity,
session store, config, transport.
Done when: unit tests show nothing is stored or sent before consent;
consent arriving later starts the SDK; a failed config fetch leaves the
SDK inert; transport batches and falls back correctly.

**M2: Signals and features.** Collectors, registry, features assembly.
Done when: tests with fake timers and a mocked IntersectionObserver
verify each feature, including dwell pausing when the tab is hidden and
session-scoped features surviving a simulated navigation.

**M3: Rules and decisions.** Condition interpreter, once-per-session
firing, fire_seq, arm assignment, coverage lookup, latency sampling.
Done when: tests cover each starting rule firing and not firing on
noise, no re-fire on repeated ticks, stable arm per visitor, arm split
within 49 to 51 percent over 10,000 random visitors, has_content false
when coverage is missing.

**M4: Shopify adapter and outcomes.** Page context, cart value,
add-to-cart detection, cart attribute, checkout pixel snippet.
Done when: adapter tests pass against the demo store markup and every
unverified Shopify assumption is listed in NOTES.md.

**M5: Backend.** Models, Alembic migration, ingest, config, consent
ping, order webhook, hardening.
Done when: pytest covers valid and invalid batches, text/plain bodies,
duplicate event ids, origin rejection, HMAC pass and fail, and the
session_rollup view on a small fixture.

**M6: Merchant data audit.** Protocol, Shopify implementation with
fixtures, audit script.
Done when: fixture-based tests pass and the script runs in dry mode.

**M7: Demo store, E2E and simulator.** Static product, cart and policy
pages. Playwright drives the real bundle: grant consent, scroll, open
the size chart, visit the shipping policy, return, add to cart.
The simulator writes sessions with planted ground truth (known
addressable share, trigger rates and a known signal effect).
Done when: `make e2e` shows the expected rows in the database, including
a delivery rule firing exactly once after the policy-page round trip,
and no rows when consent is declined.

**M8: Gate report.** rollup, gates, AUC, report.
Done when: on simulated data the report recovers the planted values
within tolerance (asserted in a test), prints all eight numbers with
thresholds, and labels the output as simulated. `make size` fails the
build above 10,240 bytes gzipped.

## 11. Out of scope for Phase 0

No card, popup, avatar or voice. No interventions. No LLM anywhere. No
bandit or uplift model. No App Store submission. No payments. No merchant
dashboard. No on-page survey. If a task seems to need one of these, stop
and write the question in NOTES.md.

## 12. Conventions

- Tests pass before a milestone is reported done. Report failures
  honestly; do not weaken a test to make it pass.
- No secrets in the repo. Everything configurable is in `.env.example`.
- Type hints and mypy in Python; strict mode in TypeScript.
- Commit messages: `phase0(M<n>): <what>`.
- Ambiguity: do not guess silently. Write the question and the
  interpretation you chose in NOTES.md, pick the option that captures
  less data and does less to the host page, and continue.
- External API facts (Shopify privacy API, pixels, cart attributes,
  Admin API): verify against current documentation. If you cannot,
  implement behind the interface, and list the item as UNVERIFIED in
  NOTES.md with what needs checking on a real shop.

## 13. Final report

After M8, report:

- What was built, per milestone.
- Test results: counts, and any skipped or failing tests.
- Bundle size in bytes gzipped.
- The gate report on simulated data, labelled as a pipeline check.
- The UNVERIFIED list and what is needed from a pilot shop to close it.
- Open questions from NOTES.md.

Begin with M0.
