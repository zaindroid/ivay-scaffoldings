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
| A17 | §8.1 | Consent is checked before the config is fetched, but `required_consent` lives in the config. | Init option `purposes` (default `["analytics"]`) gates the config fetch. After the fetch the config's `required_consent` is checked too; if it asks for more, the SDK stays inert and a later consent change retries. Nothing is stored before both pass. The config GET carries no identifier. |
| A18 | §8.1 | What is `configBase`? | Config URL is `${configBase}/${shopId}.json`. Dev: `http://localhost:8080/config`. The API (M5) serves the same at `/v1/config/{shop_id}.json` as well as without the suffix. |
| A19 | §8.3 | "Session cookie, 30 minutes of inactivity" : a pure session cookie has no inactivity timeout. | `ivay_sid` is written with `Max-Age=1800` and renewed on every touch (page load, each flush), so 30 idle minutes ends it. The pixel reads the same cookie. A new session id resets the sessionStorage state. |
| A20 | §8.3 | Spec says Secure cookies. | `Secure` is added on https pages only, so `http://localhost` dev works in every browser. Production shops are https. |
| A21 | §8.1 | "fetch, validate, cache" config. | No client-side cache: it would be another storage write. The config is served `Cache-Control` by the server, so the HTTP cache does the job. |
| A22 | §4, A14 | SDK-side contract test. | The SDK cannot ship a JSON Schema validator in 10 KB, so `src/config.ts` has a hand-written validator. `tests/contract.test.ts` runs every shared fixture through it (valid must pass, invalid must fail; the manifest pointer is checked only on the API side) and validates envelopes the SDK builds against the real schema with Ajv (dev dependency only). |
| A23 | §8.2 | Cookie provider has no change event. | Polls `document.cookie` once a second until granted, then stops. |
| A24 | §8.8 | Fetch fallback headers. | No headers are set, so the request stays a CORS-simple `text/plain` POST, identical to sendBeacon, and needs no preflight. |
| A25 | §8.4 | Dwell on a block taller than twice the viewport can never be 50% in view. | Rule as written: ratio >= 0.5. Such a block never counts. Only the first element matching each block selector is observed; blocks that render after start are picked up on `load`. |
| A26 | §8.4 | Context features (`page_type`, `device`, `cart_value`) in the features snapshot? | Yes, those three, because the gate AUC baseline needs them per session and rules may use them. `product_id` and `country` are not duplicated there: they are on `page_view`. |
| A27 | §8.4 | Session-scoped features are per tab (sessionStorage). | A shipping-policy visit in another tab is not seen. Accepted: spec says sessionStorage, and it stores less than a cross-tab store. |
| A28 | §8.4 | "Tap" and "variant change" event types. | `repeated_taps_5s` counts `click` events (capture, passive). `variant_toggles_since_atc` counts `change` events bubbling from an element matching `variant_selector`. See S3. |
| A29 | §8.4 | Re-evaluation while dwelling. | A 1 s ticker runs only while a block is in view and the tab visible, so a dwell threshold can be crossed without other events. |
| A30 | §8.6 | Leaf on a feature the SDK does not know (A7), or a null feature such as `cart_value` before `/cart.js` returns. | The leaf is false. In an `all` the rule cannot fire; in an `any` the other branches still can. No error, no log. |
| A31 | §8.7 | `mode: "live"` in the config while live mode is not built. | The SDK behaves exactly as in shadow (renders nothing, `play` and `propensity` null) and logs `mode` as configured. Play selection (uniform, propensity = 1/plays) is left for Phase 1. |
| A32 | §8.7 | Format of `content_ref`. | Delivery and returns use the string in the config (`shipping_eta:DE`). Sizing has a product-id list only, so the ref is `size_chart:<product_id>`. |
| A33 | §8.7 | Arm is computed from `visitor_hash` (already salted) and salted again. | As specified: SHA-256(visitor_hash + holdout_salt). Computed once at boot. |
| A34 | §8.6 | Rule ties on `priority`. | Broken by rule id so the order is deterministic. Rules are sorted once at start. |
| A35 | §8.6 | Latency sample storage. | Up to 2,000 samples kept (then overwritten in place) so memory is bounded; p50 is the lower median; values in microseconds rounded to 0.1. |
| A36 | §8.4 | `page_summary` timing. | Queued on `pagehide` only (spec), once per page, before the final flush. A browser that skips `pagehide` (some mobile cases) loses the summary; `rule_fired` and outcomes are unaffected because they flush on `visibilitychange`. |
| A37 | M3 test | The 49 to 51 percent arm-split test over 10,000 visitors. | With 10,000 visitors the standard deviation is 0.5 points, so 49 to 51 holds about 95% of the time for any random draw. The test uses a seeded generator so it is deterministic. The first seed tried (20240607) passed; no seed was searched for. Do not change the seed to "fix" a failure: it would mean `assignArm` changed. |
| A38 | §8.5 | Device classification. | Width below 768 px is `mobile`; otherwise a coarse pointer is `tablet`, else `desktop`. |
| A39 | §8.5 | Shopify `country`. | `Shopify.country` is the market or localization country the shopper selected, not a geolocation. That is what the content coverage index is keyed on, and it needs no extra lookup. |
| A40 | §8.5 | Cart attribute key. | `ivay_sid`, the same name as the cookie. It is written only when `/cart.js` (already fetched for the cart value) shows a different value, so there is no extra write per page. If `/cart.js` cannot be read, nothing is written. See S8. |
| A41 | §8.9 | How the pixel finds the session id. | First from the cart attribute in `data.checkout.attributes` (documented), then from `browser.cookie.get("ivay_sid")`. With neither it sends nothing, so no outcome exists for a shopper without a consented SDK session. Event ids are `pxstart_<sid>` / `pxorder_<sid>` so repeats deduplicate. |
| A42 | §8.5 | Add-to-cart outcome value. | `null`: the SDK does not know the line price. The session's cart value is in the feature snapshots. |
| A43 | M1 bug | `stop()` during the async start-up did not stop the boot. | Found when an M4 test leaked cookies into the next test. Fixed in `index.ts` (check after the digests) with a regression test. Not a test weakening. |
| A44 | §9.2 | "Validate against the envelope schema" at runtime. | The API validates with the Pydantic models in `app/schemas.py` (strict, `extra=forbid`), not with a JSON Schema library, so the schema files need not ship in the image. `tests/test_contracts_pydantic.py` runs every shared fixture and 14 hand-made edge cases through both and requires agreement. Closes the API half of A14. |
| A45 | §9.2 | Order of checks and status codes on `POST /v1/events`. | body size 413, JSON or schema 422 (never echoes the input), unknown shop 404, rate limit 429 (with `Retry-After`), Origin 403, then the insert in one transaction. Schema errors are therefore visible to any caller; they leak nothing but field paths. |
| A46 | §9.3 | Origin check details. | Exact string match against `shop.allowed_origins`. A missing Origin header is refused (browsers always send it on cross-origin POSTs, so its absence means a non-browser client). `OPTIONS` preflight answers for the union of all shops' origins because a preflight has no shop id. The SDK never preflights. See S10 for the pixel. |
| A47 | §9.3 | "Basic rate limit per shop." | In-memory sliding window per shop, default 600 requests per minute (`RATE_LIMIT_PER_MINUTE`). It is per process, so N workers or replicas allow N times that. Unknown shop ids share one bucket so probing cannot grow memory. Fine for a pilot; a shared store is needed before scale. |
| A48 | §9.2 | The webhook must find the shop but the `shop` table has no domain column (columns are fixed by the spec). | The webhook URL carries `?shop_id=<id>`, set when the merchant creates the subscription. The HMAC then proves the sender. |
| A49 | §9.1 | What `webhook_secret_ref` holds. | The name of an environment variable, which must start with `IVAY_WEBHOOK_SECRET_` (so a bad row cannot read `DATABASE_URL`). The secret itself is never in the database or the repo. No secret configured or set means 401. |
| A50 | §9.2 | "Deduplicate against the pixel's outcome by session." | A partial unique index allows one `order_completed` per (shop, session). The webhook wins: it replaces a pixel row (taking the order value) and is never replaced by one. Redelivery changes nothing. The pixel can report a different value (presentment currency) than the webhook (shop currency, S11), so the webhook value is authoritative. |
| A51 | §9.2 | Webhook topics and response. | Only `orders/create` and `orders/paid` are processed. Other topics and orders without a usable `ivay_sid` are acknowledged with 204 and ignored, so Shopify does not retry them. A missing or bad signature is 401, which Shopify treats as a failure. |
| A52 | §9.3 | Client timestamps. | `received_at` is always the server clock. The client `ts` is stored as given; above year 2100 it is a 422. Analysis should prefer `received_at` when `ts` is implausible. |
| A53 | §7.1, A15 | The 50 KB config limit. | Enforced when serving: an over-limit or invalid stored config is a generic 500 (logged), so a bad row makes the SDK inert rather than misbehave. The full fixture config is 1.7 KB. |
| A54 | §9.2 | Config caching. | `Cache-Control: public, max-age=60` plus `ETag` and 304. A kill switch therefore reaches a page within a minute of the next page load. `.json` suffix accepted because the SDK appends it. |
| A55 | §9.3 | Public surface. | `/docs`, `/redoc` and `/openapi.json` are disabled. |
| A56 | §9.1 | `session_rollup` definitions. | Final session-scoped features come from the latest snapshot across page summaries and decision logs (so a session whose `pagehide` summary was lost still has values). `arm` is taken from the first decision; sessions with no decision have a null arm, so M8 recomputes the arm from `visitor_hash` and the salt. "Touched shipping/returns/size" is the session feature OR a dwell above zero on the block. |
| A57 | env | Test database lifecycle. | `tests/conftest.py` runs `alembic downgrade base` then `upgrade head` on `ivay_test` once per session and truncates per test. That database is wiped on every run; never point `TEST_DATABASE_URL` at a real one. The container runs `alembic upgrade head` on start. |
| A58 | env | Python version. | mypy caught PEP 695 generics (3.12 syntax) in code for a 3.11 image. Replaced with `TypeVar`. |
| A59 | env | Test DB host. | The test default is `127.0.0.1`, not `localhost`: on this Windows machine `localhost` costs about 2.1 s per connection (IPv6 attempt first), which made the suite several times slower. |
| A60 | §9.4 | What "complete rates" means for a shipping country. | A country is covered when, in every delivery profile that lists it, a zone containing it has at least one active method with a rate: a fixed price (0.00 counts, free shipping is a rate) or a carrier-calculated rate. A country missing a rate in any profile that ships to it is incomplete, which is the conservative reading. The rest-of-world zone is not a country and is not counted. The script prints the complete and incomplete country codes so they can seed `content.delivery_uncertainty.by_country`. |
| A61 | §9.4 | "Share of products with a size chart." Shopify has no native size chart object. | A product is covered when a configurable metafield (default `custom.size_chart`, set with `SHOPIFY_SIZE_CHART_METAFIELD`) has a non-empty value. Only active products are counted (shoppers cannot see others). See S14. |
| A62 | §9.4 | "Whether a return policy exists." | Covered 1 of 1 when a `REFUND_POLICY` shop policy has a non-empty body, else 0 of 1. The body is read only to test that it is not blank; it is neither stored nor printed. |
| A63 | §9.4 | "Dry mode." | `--dry` replays `api/app/platforms/sample_data/dry_run.json` through the real Shopify platform code, with no network and no credentials, and the output is labelled `DRY RUN`. Without `--dry` and without credentials the script prints what to set and exits 2. |
| A64 | §9.4 | Truncated connections. | Nested connections (zones, methods) are read 50 at a time without paging. If one reports `hasNextPage`, the audit adds a WARNING to its output instead of silently undercounting. Top-level pages (profiles, products) are followed to the end, with a 400-page guard that also warns. |
| A65 | env | `httpx` is now a runtime dependency of the API package (the Shopify client uses it); `pytest-asyncio` joined the dev extras with `asyncio_mode = "auto"`. | No effect on the Phase 0 endpoints. |

## Contract fixtures

`contracts/fixtures/manifest.json` maps each invalid fixture to the JSON pointer where its
validation error must appear, so a fixture cannot start failing for an unrelated reason. The API
test also checks that the manifest and the directory list the same files.

## Unverified Shopify assumptions

Each entry says VERIFIED (read in shopify.dev docs during this build) or UNVERIFIED (what to check on a real shop).

- **S1 Customer Privacy API, VERIFIED (docs)**: `window.Shopify.customerPrivacy` with
  `analyticsProcessingAllowed()`, `marketingAllowed()`, `preferencesProcessingAllowed()`,
  `saleOfDataAllowed()` (booleans), loaded via `Shopify.loadFeatures([{name:'consent-tracking-api',
  version:'0.1'}], cb)`; change event `visitorConsentCollected` on `document`, detail
  `{marketingAllowed, saleOfDataAllowed, analyticsAllowed, preferencesAllowed}`. The SDK uses the
  `*Allowed()` calls and the event, not the detail.
- **S3 Variant change events, UNVERIFIED**: the default `variant_selector` assumes the theme's
  variant inputs fire a bubbling DOM `change` event. Dawn-style themes using `variant-selects` do,
  but themes that swap variants with custom JS may not. Check on the pilot theme that
  `variant_toggles_since_atc` increments when a shopper picks a size, and adjust the selector in config.
- **S4 `/cart.js` amount units, VERIFIED (docs)**: `total_price` is an integer in the smallest unit of
  the presentment currency (cents) with a `currency` field; `attributes` is an object. The SDK divides
  by 100. UNVERIFIED: zero-decimal currencies (JPY, KRW). Check the value on a shop in such a currency.
- **S5 Cart attributes, VERIFIED (docs)**: `POST /cart/update.js` with `{"attributes": {"key": "value"}}`
  and the attribute comes back in `attributes`. UNVERIFIED on a real shop: (a) that it reaches the order
  (Admin API `customAttributes` / webhook `note_attributes`); (b) whether the shopper sees it
  (checkout, order status page, emails) or only the merchant in the order admin. If shoppers see it,
  consider a `_`-prefixed key and change `IVAY_ATTR` together with the webhook reader.
- **S6 Checkout events, VERIFIED (docs)**: `checkout_started` and `checkout_completed` are standard
  events; `data.checkout.totalPrice.amount` (number or null), `data.checkout.attributes`
  (`[{key, value}]`), `data.checkout.token`, `data.checkout.order.id` (only on completed).
  Custom pixels use `analytics.subscribe(name, handler)`; `browser.cookie.get(name)` is async and
  reads the top frame's cookies; `browser.sendBeacon` is deprecated in favour of `fetch` with
  `keepalive: true` (used). UNVERIFIED: whether the storefront `ivay_sid` cookie is readable from the
  checkout context on this shop (why the cart attribute is primary); the custom pixel "Permission"
  setting (set to Analytics so it follows consent); the page for custom pixel sandbox limits returned 404, so network
  access to a third-party origin from the sandbox is assumed, not confirmed.
- **S7 Storefront globals, UNVERIFIED (not in official docs)**: `window.ShopifyAnalytics.meta.product.id`
  (widely used, undocumented, and absent in the theme editor preview), `window.Shopify.country`
  (present in Shopify's inlined globals per community sources), `window.Shopify.routes.root`
  (mentioned in the Ajax API docs for locale-aware URLs). Check on the pilot shop: each one exists on a
  live product page, `ShopifyAnalytics.meta.product.id` equals the Admin product id the merchant audit
  (M6) uses, and `Shopify.country` changes with the market selector.
- **S8 Add-to-cart detection, UNVERIFIED**: the adapter listens for a `submit` event on the form matching
  `add_to_cart_form`, in the capture phase, so themes that `preventDefault` and call `/cart/add.js`
  (Dawn does) are still seen. The spec's "theme cart events where available" is not implemented: there is
  no documented cross-theme DOM cart event, and none is invented. Themes that add to cart from a
  button click without a form submit are not detected. Check on the pilot theme. A submit is an attempt:
  a sold-out rejection still counts.
- **S9 Order webhook, partly VERIFIED (docs)**: HMAC is base64 HMAC-SHA256 of the raw body keyed with the
  app's client secret in the `X-Shopify-Hmac-SHA256` header; success is a 2xx (docs say 200 OK; we send 204);
  Shopify times out after 5 s. The Order resource documents `note_attributes` as `[{name, value}]` and
  `total_price` as a string in the shop currency. UNVERIFIED: that the `orders/create` and `orders/paid`
  webhook bodies contain `note_attributes` with the `ivay_sid` the SDK wrote (the webhook payload examples
  were not in the page we could read), and that they do for the API version the subscription uses. On a
  real shop: place a test order from a session with the SDK running, capture the webhook body, and confirm
  `note_attributes` and `total_price`. Also confirm 204 is accepted as success.
- **S10 Origin of pixel requests, UNVERIFIED**: the custom pixel runs in Shopify's sandbox, and the `Origin`
  header its `fetch` sends (the shop domain, `null`, or a Shopify domain) was not found in the docs. The
  API refuses any Origin not in `shop.allowed_origins`, so pixel outcomes are rejected until that value is
  added. Check the API access in the pilot (a 403 on `/v1/events` from a checkout) and add the observed
  origin. Until then the webhook still records `order_completed`.
- **S11 Currency, UNVERIFIED**: the pixel sends `data.checkout.totalPrice.amount` and the webhook sends
  `total_price` (shop currency). For a shop selling in several currencies these differ. The gate report
  does not use order values; do not compare them without converting.
- **S12 Admin GraphQL field names, VERIFIED (docs, names only)**: `deliveryProfiles(first, after)` with
  `pageInfo` and `nodes`; `DeliveryProfile.profileLocationGroups`; `locationGroupZones` with `zone`
  (`DeliveryZone`: `id`, `name`, `countries`) and `methodDefinitions` (`DeliveryMethodDefinition`: `active`,
  `id`, `name`, `rateProvider`, a union of `DeliveryParticipant` and `DeliveryRateDefinition`, whose `price` is
  `MoneyV2!`); `DeliveryCountry.code` with `countryCode` and `restOfWorld`; `shop.shopPolicies` with `type`
  (`REFUND_POLICY`, `SHIPPING_POLICY` ...), `url`, `body`; `products(first, after, query)` and
  `Product.metafield(namespace, key)` returning `value`. Scopes: `read_legal_policies` (documented),
  shipping objects need a shipping scope (`read_shipping` assumed), `read_products`.
- **S13 Audit query shape, UNVERIFIED on a live shop**: the docs pages read list field names but not every
  argument or nesting (for example `first:` on `locationGroupZones`, `pageInfo` on the nested connections, the
  `status:active` product filter). The fixtures in `api/app/platforms/sample_data` and the test fixtures were
  WRITTEN FROM THE DOCUMENTED SCHEMA, not recorded from a live shop. The first live run may return a GraphQL
  error (the script prints it); fix the query in `app/platforms/shopify.py` accordingly. Also confirm the
  Admin API version default (`2025-01`) is still supported.
- **S14 Where the pilot shop keeps size charts, UNVERIFIED**: the audit assumes a product metafield. Ask
  the merchant: a metafield (which namespace and key), a page linked from the product, an app (for example a
  size chart app), or an image in the description. Only the first is measured today.
- **S2 Consent API timing, UNVERIFIED**: the SDK does not call `loadFeatures`; it assumes the
  theme or Shopify's banner has loaded the API, and treats a missing API as "not granted". Check on a
  real shop: (a) `Shopify.customerPrivacy` exists when the SDK script runs, or how late it appears
  (if it appears without firing `visitorConsentCollected`, the SDK never starts); (b) what
  `analyticsProcessingAllowed()` returns in a region with no banner or before any choice.

## Blockers

- **B1 CI workflow cannot be pushed from this machine.** The `gh` token has no `workflow` scope, so
  GitHub rejects any commit touching `.github/workflows/`. The intended new CI (an `sdk` job: tsc,
  vitest, size gate; later analysis and e2e jobs) is kept in `docs/ci.pending.yml`. To apply:
  `gh auth refresh -s workflow`, then `cp docs/ci.pending.yml .github/workflows/ci.yml`, commit, push.
  Also note the existing `compose` job uses port 8000 and `docker compose`, which is fine on CI.

## Open questions for the owner

1. A12: confirm or replace the gate thresholds when M8 proposes them.
2. Should `required_consent` accept only Shopify's consent categories, or any string? M0 accepts
   any non-empty string; revisit after M1 verifies the Shopify API.
