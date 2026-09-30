import { readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { assignArm, lookupContent } from "../src/decision";
import { evalCondition, createRuleEngine } from "../src/rules";
import { createSessionStore } from "../src/session-store";
import { initIvay } from "../src/index";
import type { Features, NewEvent, PageContext, PageType, ShopConfig } from "../src/types";
import { CONTRACTS, fullConfig, mockFetchJson, resetBrowserState } from "./helpers";

const baseFeatures = (over: Features = {}): Features => ({
  page_type: "product", device: "desktop", cart_value: null,
  shipping_block_dwell_s: 0, returns_block_dwell_s: 0, size_block_dwell_s: 0,
  scroll_reversals_30s: 0, variant_toggles_since_atc: 0, repeated_taps_5s: 0,
  shipping_page_visited: false, returns_page_visited: false, size_chart_opens: 0,
  tab_hidden_count: 0, pages_viewed: 1, cart_adds: 0,
  ...over,
});

function engine(opts: { config?: ShopConfig; page?: Partial<PageContext>; sid?: string; arm?: "holdout" | "treatment" } = {}) {
  const sent: NewEvent[] = [];
  const page: PageContext = { page_type: "product", device: "desktop", product_id: "4821", country: "DE", ...opts.page };
  const session = createSessionStore(opts.sid ?? "sid-rules");
  const e = createRuleEngine({
    config: opts.config ?? fullConfig(), page, session, arm: opts.arm ?? "treatment", send: (x) => sent.push(x),
  });
  const fired = () => sent.filter((x) => x.type === "rule_fired") as Array<Extract<NewEvent, { type: "rule_fired" }>>;
  return { e, sent, fired, session };
}

beforeEach(resetBrowserState);

describe("condition interpreter", () => {
  const f = { a: 5, b: true, c: "x", n: null } as Features;
  const leaf = (op: string, v: boolean | number | string, name = "a") => ({ f: name, op, v }) as never;
  it("implements eq, gte, lte, gt, lt", () => {
    expect(evalCondition(leaf("eq", 5), f)).toBe(true);
    expect(evalCondition(leaf("eq", 6), f)).toBe(false);
    expect(evalCondition(leaf("gte", 5), f)).toBe(true);
    expect(evalCondition(leaf("gte", 6), f)).toBe(false);
    expect(evalCondition(leaf("lte", 5), f)).toBe(true);
    expect(evalCondition(leaf("lte", 4), f)).toBe(false);
    expect(evalCondition(leaf("gt", 5), f)).toBe(false);
    expect(evalCondition(leaf("gt", 4), f)).toBe(true);
    expect(evalCondition(leaf("lt", 6), f)).toBe(true);
    expect(evalCondition(leaf("lt", 5), f)).toBe(false);
  });
  it("eq works on booleans and strings; ordering ops need numbers", () => {
    expect(evalCondition(leaf("eq", true, "b"), f)).toBe(true);
    expect(evalCondition(leaf("eq", "x", "c"), f)).toBe(true);
    expect(evalCondition(leaf("gte", 1, "b"), f)).toBe(false);
    expect(evalCondition(leaf("gte", 1, "c"), f)).toBe(false);
    expect(evalCondition(leaf("eq", "5"), f)).toBe(false); // no coercion
  });
  it("unknown or null feature is false, in any position", () => {
    expect(evalCondition(leaf("gte", 0, "nope"), f)).toBe(false);
    expect(evalCondition(leaf("eq", 0, "n"), f)).toBe(false);
    expect(evalCondition({ any: [leaf("gte", 0, "nope"), leaf("eq", 5)] }, f)).toBe(true);
    expect(evalCondition({ all: [leaf("gte", 0, "nope"), leaf("eq", 5)] }, f)).toBe(false);
  });
  it("all and any nest", () => {
    const c = { any: [leaf("eq", 1), { all: [leaf("eq", 5), leaf("eq", true, "b")] }] };
    expect(evalCondition(c as never, f)).toBe(true);
    expect(evalCondition({ all: [c, leaf("eq", 9)] } as never, f)).toBe(false);
  });
});

describe("starting rules fire, and do not fire on noise", () => {
  it("delivery fires when the shipping policy page was visited", () => {
    const t = engine();
    t.e.evaluate(baseFeatures({ shipping_page_visited: true }));
    expect(t.fired().map((x) => x.friction_state)).toEqual(["delivery_uncertainty"]);
  });
  it("delivery fires on long shipping-block dwell plus scroll reversals, on the cart page too", () => {
    const t = engine({ page: { page_type: "cart" } });
    t.e.evaluate(baseFeatures({ shipping_block_dwell_s: 40, scroll_reversals_30s: 2 }));
    expect(t.fired()).toHaveLength(1);
  });
  it("delivery does not fire on noise: dwell alone, reversals alone, short dwell, unrelated signals", () => {
    const t = engine();
    t.e.evaluate(baseFeatures({ shipping_block_dwell_s: 120 }));
    t.e.evaluate(baseFeatures({ scroll_reversals_30s: 9 }));
    t.e.evaluate(baseFeatures({ shipping_block_dwell_s: 39, scroll_reversals_30s: 5 }));
    t.e.evaluate(baseFeatures({ returns_block_dwell_s: 99, size_block_dwell_s: 99, repeated_taps_5s: 9, tab_hidden_count: 9 }));
    expect(t.fired()).toHaveLength(0);
  });
  it("returns fires after a returns-policy visit, not before", () => {
    const t = engine();
    t.e.evaluate(baseFeatures());
    expect(t.fired()).toHaveLength(0);
    t.e.evaluate(baseFeatures({ returns_page_visited: true }));
    expect(t.fired().map((x) => x.friction_state)).toEqual(["returns_uncertainty"]);
  });
  it("sizing fires on two size-chart opens or three variant toggles, product pages only", () => {
    const a = engine({ sid: "s-a" });
    a.e.evaluate(baseFeatures({ size_chart_opens: 1, variant_toggles_since_atc: 2 }));
    expect(a.fired()).toHaveLength(0);
    a.e.evaluate(baseFeatures({ size_chart_opens: 2 }));
    expect(a.fired().map((x) => x.friction_state)).toEqual(["sizing_uncertainty"]);
    const b = engine({ sid: "s-b" });
    b.e.evaluate(baseFeatures({ variant_toggles_since_atc: 3 }));
    expect(b.fired()).toHaveLength(1);
    const cart = engine({ sid: "s-c", page: { page_type: "cart" } });
    cart.e.evaluate(baseFeatures({ size_chart_opens: 5, variant_toggles_since_atc: 5 }));
    expect(cart.fired()).toHaveLength(0);
  });
  it("no rule is eligible on other page types", () => {
    for (const page_type of ["shipping_policy", "returns_policy", "other"] as PageType[]) {
      const t = engine({ page: { page_type }, sid: `s-${page_type}` });
      t.e.evaluate(baseFeatures({ shipping_page_visited: true, returns_page_visited: true, size_chart_opens: 9 }));
      expect(t.fired()).toHaveLength(0);
    }
  });
  it("a config with no rules does nothing", () => {
    const t = engine({ config: { ...fullConfig(), rules: [] } });
    t.e.evaluate(baseFeatures({ shipping_page_visited: true }));
    expect(t.sent).toHaveLength(0);
  });
});

describe("once per session, fire_seq, priority", () => {
  it("does not re-fire on repeated ticks", () => {
    const t = engine();
    const f = baseFeatures({ shipping_page_visited: true });
    for (let i = 0; i < 50; i++) t.e.evaluate(f);
    expect(t.fired()).toHaveLength(1);
  });
  it("does not re-fire on a later page of the same session, but does in a new session", () => {
    const f = baseFeatures({ shipping_page_visited: true });
    engine({ sid: "s-x" }).e.evaluate(f);
    const later = engine({ sid: "s-x" });
    later.e.evaluate(f);
    expect(later.fired()).toHaveLength(0);
    const fresh = engine({ sid: "s-y" });
    fresh.e.evaluate(f);
    expect(fresh.fired()).toHaveLength(1);
  });
  it("several rules in one tick fire in priority order with consecutive fire_seq", () => {
    const t = engine();
    t.e.evaluate(baseFeatures({ shipping_page_visited: true, returns_page_visited: true, size_chart_opens: 2 }));
    expect(t.fired().map((x) => [x.friction_state, x.fire_seq])).toEqual([
      ["delivery_uncertainty", 1], ["returns_uncertainty", 2], ["sizing_uncertainty", 3],
    ]);
  });
  it("priority, not config order, decides the sequence", () => {
    const c = fullConfig();
    const by = Object.fromEntries(c.rules.map((r) => [r.friction_state, r]));
    by.delivery_uncertainty.priority = 9;
    by.returns_uncertainty.priority = 5;
    by.sizing_uncertainty.priority = 0;
    const t = engine({ config: c });
    t.e.evaluate(baseFeatures({ shipping_page_visited: true, returns_page_visited: true, size_chart_opens: 2 }));
    expect(t.fired().map((x) => [x.friction_state, x.fire_seq])).toEqual([
      ["sizing_uncertainty", 1], ["returns_uncertainty", 2], ["delivery_uncertainty", 3],
    ]);
  });
  it("fire_seq continues across ticks and pages: first-fired state is chronologically first", () => {
    const a = engine({ sid: "s-seq" });
    a.e.evaluate(baseFeatures({ returns_page_visited: true }));
    a.e.evaluate(baseFeatures({ returns_page_visited: true, shipping_page_visited: true }));
    expect(a.fired().map((x) => [x.friction_state, x.fire_seq])).toEqual([
      ["returns_uncertainty", 1], ["delivery_uncertainty", 2],
    ]);
    const b = engine({ sid: "s-seq" });
    b.e.evaluate(baseFeatures({ size_chart_opens: 2 }));
    expect(b.fired()[0].fire_seq).toBe(3);
  });
  it("two rules for the same friction state fire only once", () => {
    const c = fullConfig();
    c.rules.push({ ...c.rules[0], id: "delivery_v2", priority: 5 });
    const t = engine({ config: c });
    t.e.evaluate(baseFeatures({ shipping_page_visited: true }));
    expect(t.fired()).toHaveLength(1);
    expect(t.fired()[0].rule_id).toBe("delivery_v1");
  });
});

describe("decision content", () => {
  it("shadow mode: play and propensity are null; rule id, version, arm, mode and features are logged", () => {
    const t = engine({ arm: "holdout" });
    const f = baseFeatures({ shipping_page_visited: true });
    t.e.evaluate(f);
    const d = t.fired()[0];
    expect(d).toMatchObject({
      play: null, propensity: null, rule_id: "delivery_v1", rule_version: "r1", arm: "holdout", mode: "shadow",
    });
    expect(d.features).toEqual(f);
    expect(d.decision_id).toMatch(/^[0-9a-f]{24}$/);
  });
  it("has_content follows the coverage index", () => {
    const c = fullConfig();
    expect(lookupContent(c, "delivery_uncertainty", { product_id: "1", country: "DE" })).toEqual({ content_ref: "shipping_eta:DE", has_content: true });
    expect(lookupContent(c, "returns_uncertainty", { product_id: null, country: null })).toEqual({ content_ref: "returns_policy:v1", has_content: true });
    expect(lookupContent(c, "sizing_uncertainty", { product_id: "4821", country: null })).toEqual({ content_ref: "size_chart:4821", has_content: true });
  });
  it("has_content is false when coverage is missing", () => {
    const c = fullConfig();
    const none = { content_ref: null, has_content: false };
    expect(lookupContent(c, "delivery_uncertainty", { product_id: "1", country: "FR" })).toEqual(none);
    expect(lookupContent(c, "delivery_uncertainty", { product_id: "1", country: null })).toEqual(none);
    expect(lookupContent(c, "sizing_uncertainty", { product_id: "999", country: "DE" })).toEqual(none);
    expect(lookupContent(c, "sizing_uncertainty", { product_id: null, country: "DE" })).toEqual(none);
    expect(lookupContent({ ...c, content: {} }, "returns_uncertainty", { product_id: null, country: null })).toEqual(none);
    expect(lookupContent({ ...c, content: {} }, "delivery_uncertainty", { product_id: null, country: "DE" })).toEqual(none);
  });
  it("a fired rule with no coverage is still logged, with has_content false", () => {
    const t = engine({ page: { country: "FR" } });
    t.e.evaluate(baseFeatures({ shipping_page_visited: true }));
    expect(t.fired()[0]).toMatchObject({ content_ref: null, has_content: false });
  });
});

describe("arm assignment", () => {
  it("is stable per visitor and independent of anything else", async () => {
    const a = await assignArm("v".repeat(64), "salt", 5000);
    for (let i = 0; i < 5; i++) expect(await assignArm("v".repeat(64), "salt", 5000)).toBe(a);
  });
  it("edge holdout_bps: 0 is all treatment, 10000 is all holdout", async () => {
    for (let i = 0; i < 50; i++) {
      expect(await assignArm(`visitor-${i}`, "s", 0)).toBe("treatment");
      expect(await assignArm(`visitor-${i}`, "s", 10000)).toBe("holdout");
    }
  });
  it("matches the spec formula exactly", async () => {
    const { sha256Hex } = await import("../src/identity");
    const h = await sha256Hex("visitor-1" + "salt");
    const expected = parseInt(h.slice(0, 8), 16) % 10000 < 5000 ? "holdout" : "treatment";
    expect(await assignArm("visitor-1", "salt", 5000)).toBe(expected);
  });
  it("splits 49 to 51 percent over 10,000 visitors (seeded, so the test is deterministic)", async () => {
    let seed = 20240607;
    const rnd = () => {
      seed = (seed + 0x6d2b79f5) | 0;
      let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    let holdout = 0;
    for (let i = 0; i < 10000; i++) {
      const visitor = Array.from({ length: 16 }, () => Math.floor(rnd() * 256).toString(16).padStart(2, "0")).join("");
      if ((await assignArm(visitor, "fixed-public-string", 5000)) === "holdout") holdout++;
    }
    expect(holdout / 10000).toBeGreaterThanOrEqual(0.49);
    expect(holdout / 10000).toBeLessThanOrEqual(0.51);
  });
  it("a different salt reshuffles arms", async () => {
    let differ = 0;
    for (let i = 0; i < 200; i++) {
      if ((await assignArm(`v${i}`, "salt-a", 5000)) !== (await assignArm(`v${i}`, "salt-b", 5000))) differ++;
    }
    expect(differ).toBeGreaterThan(50);
  });
});

describe("latency sampling", () => {
  afterEach(() => vi.restoreAllMocks());
  it("reports count, p50 and max in microseconds", () => {
    const t = engine();
    const durations = [1, 2, 3, 4, 10]; // ms
    let now = 0;
    let call = 0;
    vi.spyOn(performance, "now").mockImplementation(() => {
      // calls alternate start/end of an evaluation
      const v = call % 2 === 0 ? now : now + durations[Math.floor(call / 2)];
      call++;
      return v;
    });
    for (let i = 0; i < 5; i++) t.e.evaluate(baseFeatures());
    expect(t.e.stats()).toEqual({ eval_count: 5, eval_p50_us: 3000, eval_max_us: 10000 });
  });
  it("is zeroed before any evaluation", () => {
    expect(engine().e.stats()).toEqual({ eval_count: 0, eval_p50_us: 0, eval_max_us: 0 });
  });
  it("stays bounded in memory over many evaluations", () => {
    const t = engine();
    for (let i = 0; i < 5000; i++) t.e.evaluate(baseFeatures());
    expect(t.e.stats().eval_count).toBe(5000);
  });
});

describe("end to end through initIvay", () => {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validate = ajv.compile(JSON.parse(readFileSync(join(CONTRACTS, "event-envelope.schema.json"), "utf8")));
  let beacons: string[];
  let handle: { stop(): void } | undefined;
  beforeEach(() => {
    beacons = [];
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: (_u: string, b: string) => (beacons.push(b), true) });
  });
  afterEach(() => {
    handle?.stop();
    vi.unstubAllGlobals();
  });
  const platform = (page_type: PageType) => ({
    getPageContext: () => ({ page_type, device: "desktop" as const, product_id: "4821", country: "DE" }),
    getCart: async () => ({ value: null }),
    onAddToCart: () => {},
    setCartAttribute: () => {},
  });
  const start = (page_type: PageType) =>
    initIvay({ shopId: "shop_dev", configBase: "http://s/config", consent: { provider: "custom", isGranted: () => true }, platform: platform(page_type) });
  const events = () => beacons.flatMap((b) => JSON.parse(b).events as Array<Record<string, unknown>>);

  it("shipping-policy round trip: rule fires exactly once on the next product page; summary on pagehide", async () => {
    mockFetchJson(fullConfig());
    handle = start("shipping_policy");
    await vi.waitFor(() => expect(sessionStorage.getItem("ivay_s")).toContain("shipping_page_visited"));
    window.dispatchEvent(new Event("pagehide"));
    handle.stop();
    expect(events().filter((e) => e.type === "rule_fired")).toHaveLength(0);
    expect(events().filter((e) => e.type === "page_summary")).toHaveLength(1);

    beacons.length = 0;
    handle = start("product");
    await vi.waitFor(() => expect(sessionStorage.getItem("ivay_s")).toContain('"fire_seq":1'));
    window.dispatchEvent(new Event("pagehide"));
    window.dispatchEvent(new Event("pagehide")); // a second pagehide must not duplicate the summary
    const ev = events();
    const fired = ev.filter((e) => e.type === "rule_fired");
    expect(fired).toHaveLength(1);
    expect(fired[0]).toMatchObject({ friction_state: "delivery_uncertainty", fire_seq: 1, has_content: true, play: null, propensity: null });
    const summary = ev.filter((e) => e.type === "page_summary");
    expect(summary).toHaveLength(1);
    expect(summary[0].eval_count as number).toBeGreaterThan(0);
    for (const b of beacons) expect(validate(JSON.parse(b)), JSON.stringify(validate.errors)).toBe(true);
  });
});
