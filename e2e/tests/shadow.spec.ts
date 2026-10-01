import { test } from "@playwright/test";
import {
  API, cookieValue, eventually, expect, ivayStorage, prepare, resetEvents, rows, totalEventRows,
} from "./helpers";

test.beforeEach(async () => {
  await resetEvents();
});

const PRODUCT = "/products/tee.html";

test("consent granted: a delivery rule fires exactly once after the shipping-policy round trip", async ({ page }) => {
  const rec = await prepare(page);

  // 1. Before any consent nothing exists, nothing is stored, nothing is sent.
  await page.goto(PRODUCT);
  await expect(page.locator("#demo-consent")).toBeVisible();
  await page.waitForTimeout(800);
  const before = await ivayStorage(page);
  expect(before).toEqual({ cookies: [], session: null, local: [] });
  expect(rec.apiRequests).toEqual([]);
  const mainBefore = await page.locator("main").innerHTML();

  // 2. Grant consent: the SDK starts without a reload.
  await page.click("#demo-consent-accept");
  await eventually(() => cookieValue(page, "ivay_sid").then((v) => v ?? ""), (v) => v.length === 24, "ivay_sid cookie");
  const sid = (await cookieValue(page, "ivay_sid"))!;
  const vid = (await cookieValue(page, "ivay_vid"))!;
  expect(sid).toMatch(/^[0-9a-f]{24}$/);
  expect(vid).toMatch(/^[0-9a-f]{32}$/);

  // 3. Scroll down and back up, open the size chart once.
  await page.mouse.move(400, 300);
  await page.mouse.wheel(0, 900);
  await page.waitForTimeout(150);
  await page.mouse.wheel(0, -300);
  await page.waitForTimeout(250);
  await page.click("#size-chart-link");

  // 4. Visit the shipping policy and come back to the product page.
  await page.goto("/policies/shipping-policy.html");
  await expect(page.locator("h1")).toHaveText("Shipping policy");
  await page.click("text=Back to the product");
  await expect(page).toHaveURL(/\/products\/tee\.html$/);

  // The rule fires on the product page after the round trip, once.
  await eventually(
    () => page.evaluate(() => window.sessionStorage.getItem("ivay_s")),
    (s) => !!s && JSON.parse(s).fired?.delivery_uncertainty === true,
    "delivery_uncertainty marked fired in the session store",
  );

  // 5. Add to cart, then leave so pagehide flushes the last page.
  await page.click("button[name=add]");
  await expect(page.locator("#demo-atc-status")).toHaveText("Added to cart");
  await page.waitForTimeout(400);
  // Shadow mode: the SDK changed nothing in the page content.
  expect((await page.locator("main").innerHTML()).replace("Added to cart", "")).toBe(mainBefore);
  await page.goto("/cart.html");
  await page.waitForTimeout(400);
  await page.goto("about:blank");

  // 6. The database has the expected rows.
  const views = await eventually(
    () => rows<{ page_type: string; session_id: string; visitor_hash: string }>("SELECT page_type, session_id, visitor_hash FROM page_view ORDER BY ts, received_at"),
    (r) => r.length >= 4,
    "four page views",
  );
  expect(views.map((v) => v.page_type)).toEqual(["product", "shipping_policy", "product", "cart"]);
  expect(new Set(views.map((v) => v.session_id))).toEqual(new Set([sid]));
  expect(views[0].visitor_hash).toMatch(/^[0-9a-f]{64}$/);

  const decisions = await eventually(
    () => rows<Record<string, unknown>>("SELECT * FROM decision_log ORDER BY fire_seq"),
    (r) => r.length >= 1,
    "a decision",
  );
  await page.waitForTimeout(500);
  const finalDecisions = await rows<Record<string, unknown>>("SELECT * FROM decision_log ORDER BY fire_seq");
  expect(finalDecisions).toHaveLength(1); // exactly once
  expect(decisions[0]).toMatchObject({
    friction_state: "delivery_uncertainty", rule_id: "delivery_v1", rule_version: "r1", fire_seq: 1,
    mode: "shadow", play: null, propensity: null, has_content: true, content_ref: "shipping_eta:DE", session_id: sid,
  });
  expect(["holdout", "treatment"]).toContain(decisions[0].arm);
  expect((decisions[0].features as Record<string, unknown>).shipping_page_visited).toBe(true);

  const outcomes = await rows<{ kind: string; source: string }>("SELECT kind, source FROM outcome_event");
  expect(outcomes).toEqual([{ kind: "add_to_cart", source: "sdk" }]);

  const summaries = await eventually(
    () => rows<{ eval_count: number; features: Record<string, unknown> }>("SELECT eval_count, features FROM page_summary"),
    (r) => r.length >= 4,
    "four page summaries",
  );
  for (const s of summaries) expect(s.eval_count).toBeGreaterThan(0);
  expect(Math.max(...summaries.map((s) => Number(s.features.scroll_reversals_30s ?? 0)))).toBeGreaterThanOrEqual(1);
  expect(Math.max(...summaries.map((s) => Number(s.features.cart_value ?? 0)))).toBe(29);

  // 7. The session carries its id to the order: a cart attribute was written once.
  expect(rec.cartUpdates).toEqual([{ attributes: { ivay_sid: sid } }]);
  expect(rec.cartReads).toBeGreaterThanOrEqual(3); // one /cart.js per page load, not per event

  // 8. The rollup the gate report reads sees the session.
  const [r] = await rows<Record<string, unknown>>("SELECT * FROM session_rollup WHERE session_id = $1", [sid]);
  expect(r).toMatchObject({
    page_views: "4", shipping_page_visited: true, size_chart_opens: 1, cart_adds: 1,
    first_fired_state: "delivery_uncertainty", has_add_to_cart: true, has_order_completed: false, abandoned: true,
  });

  // 9. The raw visitor id never reaches the server.
  const dump = JSON.stringify(await rows("SELECT * FROM page_view")) + JSON.stringify(await rows("SELECT * FROM decision_log")) +
    JSON.stringify(await rows("SELECT * FROM page_summary")) + JSON.stringify(await rows("SELECT * FROM outcome_event"));
  expect(dump).not.toContain(vid);
});

test("sizing rule fires once after the size chart is opened twice", async ({ page }) => {
  await prepare(page);
  await page.goto(PRODUCT);
  await page.click("#demo-consent-accept");
  await eventually(() => cookieValue(page, "ivay_sid").then((v) => v ?? ""), (v) => v.length === 24, "ivay_sid cookie");
  await page.click("#size-chart-link");
  await page.click("#size-chart-link");
  await page.click("#size-chart-link");
  await eventually(
    () => page.evaluate(() => window.sessionStorage.getItem("ivay_s")),
    (s) => !!s && JSON.parse(s).fired?.sizing_uncertainty === true,
    "sizing fired",
  );
  await page.goto("about:blank");
  const d = await eventually(() => rows<Record<string, unknown>>("SELECT * FROM decision_log"), (r) => r.length >= 1, "decision");
  await page.waitForTimeout(400);
  const all = await rows<Record<string, unknown>>("SELECT friction_state, fire_seq, has_content, content_ref FROM decision_log");
  expect(all).toEqual([{ friction_state: "sizing_uncertainty", fire_seq: 1, has_content: true, content_ref: "size_chart:4821" }]);
  expect(d).toHaveLength(1);
});

test("returns rule fires after a visit to the refund policy", async ({ page }) => {
  await prepare(page);
  await page.goto(PRODUCT);
  await page.click("#demo-consent-accept");
  await eventually(() => cookieValue(page, "ivay_sid").then((v) => v ?? ""), (v) => v.length === 24, "ivay_sid cookie");
  await page.goto("/policies/refund-policy.html");
  await page.click("text=Back to the product");
  await eventually(
    () => page.evaluate(() => window.sessionStorage.getItem("ivay_s")),
    (s) => !!s && JSON.parse(s).fired?.returns_uncertainty === true,
    "returns fired",
  );
  await page.goto("about:blank");
  await eventually(() => rows("SELECT 1 FROM decision_log"), (r) => r.length === 1, "one returns decision");
  const [d] = await rows<{ friction_state: string }>("SELECT friction_state FROM decision_log");
  expect(d.friction_state).toBe("returns_uncertainty");
});

test("consent declined: no cookie, no storage, no request to the API, no rows", async ({ page }) => {
  const rec = await prepare(page);
  await page.goto(PRODUCT);
  await page.click("#demo-consent-decline");

  // Do everything a shopper would do.
  await page.mouse.move(400, 300);
  await page.mouse.wheel(0, 900);
  await page.mouse.wheel(0, -300);
  await page.click("#size-chart-link");
  await page.click("#size-chart-link");
  await page.goto("/policies/shipping-policy.html");
  await page.click("text=Back to the product");
  await page.click("button[name=add]");
  await page.waitForTimeout(800);

  expect(await ivayStorage(page)).toEqual({ cookies: [], session: null, local: [] });
  expect((await page.context().cookies()).filter((c) => c.name.startsWith("ivay_"))).toEqual([]);
  expect(rec.apiRequests).toEqual([]); // not even the config fetch
  expect(rec.cartReads).toBe(0);
  expect(rec.cartUpdates).toEqual([]);

  await page.goto("/cart.html");
  await page.goto("about:blank");
  await page.waitForTimeout(800);
  expect(rec.apiRequests).toEqual([]);
  expect(await totalEventRows()).toBe(0);
});

test("consent withheld (banner ignored): nothing is stored or sent", async ({ page }) => {
  const rec = await prepare(page);
  await page.goto(PRODUCT);
  await page.mouse.wheel(0, 500);
  await page.click("#size-chart-link");
  await page.waitForTimeout(800);
  await page.goto("about:blank");
  expect(rec.apiRequests).toEqual([]);
  expect(await totalEventRows()).toBe(0);
});

test.describe("inert states", () => {
  test("kill switch: consent is granted but the SDK does nothing", async ({ page }) => {
    const rec = await prepare(page);
    const [{ config }] = await rows<{ config: Record<string, unknown> }>("SELECT config FROM shop WHERE shop_id = 'shop_dev'");
    try {
      await rows("UPDATE shop SET config = jsonb_set(config, '{kill_switch}', 'true') WHERE shop_id = 'shop_dev'");
      await page.goto(PRODUCT);
      await page.click("#demo-consent-accept");
      await page.waitForTimeout(1500);
      await page.click("#size-chart-link");
      await page.goto("about:blank");
      expect(rec.apiRequests).toEqual(["GET /v1/config/shop_dev.json"]);
      expect(await totalEventRows()).toBe(0);
    } finally {
      await rows("UPDATE shop SET config = $1::jsonb WHERE shop_id = 'shop_dev'", [JSON.stringify(config)]);
    }
  });

  test("config fetch fails: the SDK stays inert and the page still works", async ({ page }) => {
    const rec = await prepare(page);
    await page.route(`${API}/v1/config/**`, (route) => route.abort());
    const errors: string[] = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(PRODUCT);
    await page.click("#demo-consent-accept");
    await page.waitForTimeout(1000);
    await page.click("button[name=add]");
    await expect(page.locator("#demo-atc-status")).toHaveText("Added to cart");
    expect(await ivayStorage(page)).toEqual({ cookies: [], session: null, local: [] });
    expect(errors).toEqual([]);
    expect(rec.cartReads).toBe(0);
    expect(await totalEventRows()).toBe(0);
  });
});
