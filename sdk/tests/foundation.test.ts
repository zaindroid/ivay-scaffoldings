import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cookieConsent } from "../src/consent/cookie";
import { customConsent } from "../src/consent/custom";
import { shopifyConsent } from "../src/consent/shopify";
import { createGuard } from "../src/guard";
import { getVisitorId, randomId, sha256Hex, touchSession, visitorHash } from "../src/identity";
import { createSessionStore } from "../src/session-store";
import { resetBrowserState } from "./helpers";

beforeEach(resetBrowserState);
afterEach(() => {
  vi.useRealTimers();
  delete (window as unknown as { Shopify?: unknown }).Shopify;
});

describe("guard", () => {
  it("swallows sync and async errors and never throws to the caller", async () => {
    const g = createGuard(() => {});
    expect(() => g.wrap(() => { throw new Error("x"); })()).not.toThrow();
    expect(() => g.wrap(async () => { throw new Error("y"); })()).not.toThrow();
    await Promise.resolve();
  });
  it("disables itself after 5 caught errors and stops running wrapped functions", async () => {
    const off = vi.fn();
    const g = createGuard(off);
    const bad = g.wrap(() => { throw new Error("x"); });
    for (let i = 0; i < 4; i++) bad();
    expect(off).not.toHaveBeenCalled();
    bad();
    expect(off).toHaveBeenCalledTimes(1);
    expect(g.isDisabled()).toBe(true);
    const ok = vi.fn();
    g.wrap(ok)();
    expect(ok).not.toHaveBeenCalled();
  });
  it("counts rejected promises as errors", async () => {
    const off = vi.fn();
    const g = createGuard(off, 2);
    const bad = g.wrap(async () => { throw new Error("x"); });
    bad();
    bad();
    await new Promise((r) => setTimeout(r, 0));
    expect(off).toHaveBeenCalled();
  });
});

describe("consent providers", () => {
  it("shopify: not granted when the API is missing", () => {
    expect(shopifyConsent().isGranted(["analytics"])).toBe(false);
  });
  it("shopify: maps purposes to the privacy API and denies unknown purposes", () => {
    const w = window as unknown as { Shopify: unknown };
    w.Shopify = {
      customerPrivacy: {
        analyticsProcessingAllowed: () => true,
        marketingAllowed: () => false,
        preferencesProcessingAllowed: () => true,
        saleOfDataAllowed: () => true,
      },
    };
    const c = shopifyConsent();
    expect(c.isGranted(["analytics"])).toBe(true);
    expect(c.isGranted(["analytics", "preferences"])).toBe(true);
    expect(c.isGranted(["analytics", "marketing"])).toBe(false);
    expect(c.isGranted(["telepathy"])).toBe(false);
  });
  it("shopify: fires onChange on visitorConsentCollected", () => {
    const cb = vi.fn();
    shopifyConsent().onChange(cb);
    document.dispatchEvent(new Event("visitorConsentCollected"));
    expect(cb).toHaveBeenCalledTimes(1);
  });
  it("cookie: granted only when the pattern matches; polls for change", () => {
    vi.useFakeTimers();
    const c = cookieConsent("cmp", "analytics:true");
    expect(c.isGranted(["analytics"])).toBe(false);
    const cb = vi.fn();
    c.onChange(cb);
    vi.advanceTimersByTime(3000);
    expect(cb).not.toHaveBeenCalled();
    document.cookie = "cmp=analytics%3Atrue; Path=/";
    vi.advanceTimersByTime(1000);
    expect(cb).toHaveBeenCalledTimes(1);
    expect(c.isGranted(["analytics"])).toBe(true);
  });
  it("cookie: an invalid pattern never grants", () => {
    document.cookie = "cmp=x; Path=/";
    expect(cookieConsent("cmp", "(").isGranted(["analytics"])).toBe(false);
  });
  it("custom: delegates and only accepts true", () => {
    expect(customConsent(() => true).isGranted([])).toBe(true);
    expect(customConsent(() => "yes" as unknown as boolean).isGranted([])).toBe(false);
  });
});

describe("identity", () => {
  it("random ids are hex of the requested size and differ", () => {
    expect(randomId(16)).toMatch(/^[0-9a-f]{32}$/);
    expect(randomId(16)).not.toBe(randomId(16));
  });
  it("sha256 matches a known vector", async () => {
    expect(await sha256Hex("abc")).toBe(
      "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad",
    );
  });
  it("visitor id persists in the cookie and only the salted hash is derived", async () => {
    const a = getVisitorId();
    expect(a).toMatch(/^[0-9a-f]{32}$/);
    expect(getVisitorId()).toBe(a);
    const h = await visitorHash(a, "salt");
    expect(h).toMatch(/^[0-9a-f]{64}$/);
    expect(h).not.toContain(a);
  });
  it("session id is stable across touches and readable by the pixel", () => {
    const s = touchSession();
    expect(touchSession()).toBe(s);
    expect(document.cookie).toContain(`ivay_sid=${s}`);
  });
});

describe("session store", () => {
  it("round-trips through sessionStorage under one key", () => {
    const s = createSessionStore("sid1");
    s.update((x) => { x.fire_seq = 2; x.features.size_chart_opens = 1; });
    const again = createSessionStore("sid1");
    expect(again.get().fire_seq).toBe(2);
    expect(again.get().features.size_chart_opens).toBe(1);
    expect(sessionStorage.length).toBe(1);
  });
  it("a new session id resets the state", () => {
    createSessionStore("sid1").update((x) => { x.fire_seq = 5; });
    expect(createSessionStore("sid2").get().fire_seq).toBe(0);
  });
  it("survives blocked storage by keeping state in memory", () => {
    const broken = { getItem() { throw new Error("blocked"); }, setItem() { throw new Error("blocked"); } } as unknown as Storage;
    const s = createSessionStore("sid1", broken);
    s.update((x) => { x.fire_seq = 1; });
    expect(s.get().fire_seq).toBe(1);
  });
  it("ignores corrupt stored JSON", () => {
    sessionStorage.setItem("ivay_s", "{not json");
    expect(createSessionStore("sid1").get().fire_seq).toBe(0);
  });
});
