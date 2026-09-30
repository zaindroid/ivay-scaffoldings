import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createTransport } from "../src/transport";
import type { Transport } from "../src/types";

let beacons: string[];
let beaconResult: boolean;
let fetches: Array<{ url: string; init: RequestInit }>;
let t: Transport;

const ev = { type: "outcome", kind: "add_to_cart", value: null, source: "sdk" } as const;
const make = () =>
  createTransport({
    url: "http://x/v1/events",
    shopId: "shop_dev",
    identity: () => ({ visitor_hash: "a".repeat(64), session_id: "s".repeat(24), page_id: "p".repeat(24) }),
  });

beforeEach(() => {
  vi.useFakeTimers();
  beacons = [];
  fetches = [];
  beaconResult = true;
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: (_u: string, b: string) => (beaconResult ? (beacons.push(b), true) : false),
  });
  vi.stubGlobal("fetch", (url: string, init: RequestInit) => {
    fetches.push({ url, init });
    return Promise.resolve({ ok: true });
  });
  t = make();
});
afterEach(() => {
  t.stop();
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("transport", () => {
  it("sends nothing until a flush trigger", () => {
    t.send(ev);
    expect(beacons).toHaveLength(0);
  });
  it("flushes 5 s after the first event, as one batch", () => {
    t.send(ev);
    t.send(ev);
    vi.advanceTimersByTime(4999);
    expect(beacons).toHaveLength(0);
    vi.advanceTimersByTime(1);
    expect(beacons).toHaveLength(1);
    expect(JSON.parse(beacons[0]).events).toHaveLength(2);
  });
  it("flushes at 20 events", () => {
    for (let i = 0; i < 19; i++) t.send(ev);
    expect(beacons).toHaveLength(0);
    t.send(ev);
    expect(beacons).toHaveLength(1);
    expect(JSON.parse(beacons[0]).events).toHaveLength(20);
  });
  it("flushes on pagehide and when the tab becomes hidden, not when visible", () => {
    t.send(ev);
    document.dispatchEvent(new Event("visibilitychange")); // visible in happy-dom
    expect(beacons).toHaveLength(0);
    window.dispatchEvent(new Event("pagehide"));
    expect(beacons).toHaveLength(1);
    t.send(ev);
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "hidden" });
    document.dispatchEvent(new Event("visibilitychange"));
    Object.defineProperty(document, "visibilityState", { configurable: true, value: "visible" });
    expect(beacons).toHaveLength(2);
  });
  it("never listens to unload or beforeunload", () => {
    const spy = vi.spyOn(window, "addEventListener");
    const t2 = make();
    const names = spy.mock.calls.map((c) => c[0]);
    t2.stop();
    expect(names).not.toContain("unload");
    expect(names).not.toContain("beforeunload");
  });
  it("body is a JSON string (text/plain via sendBeacon) with unique event ids and timestamps", () => {
    t.send(ev);
    t.send(ev);
    t.flush();
    const b = JSON.parse(beacons[0]);
    expect(typeof beacons[0]).toBe("string");
    expect(b.shop_id).toBe("shop_dev");
    expect(b.events[0].event_id).not.toBe(b.events[1].event_id);
    expect(typeof b.events[0].ts).toBe("number");
    expect(typeof b.sent_at).toBe("number");
  });
  it("falls back to fetch keepalive when sendBeacon returns false", () => {
    beaconResult = false;
    t.send(ev);
    t.flush();
    expect(beacons).toHaveLength(0);
    expect(fetches).toHaveLength(1);
    expect(fetches[0].init.keepalive).toBe(true);
    expect(fetches[0].init.method).toBe("POST");
    expect(fetches[0].init.headers).toBeUndefined();
  });
  it("falls back to fetch when sendBeacon is missing or throws", () => {
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: undefined });
    t.send(ev);
    t.flush();
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: () => { throw new Error("x"); } });
    t.send(ev);
    t.flush();
    expect(fetches).toHaveLength(2);
  });
  it("a rejecting fetch does not throw", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
    beaconResult = false;
    t.send(ev);
    expect(() => t.flush()).not.toThrow();
    await Promise.resolve();
  });
  it("splits so every batch stays under 60 KB and loses no event", () => {
    const big = {
      type: "page_summary", features: Object.fromEntries(Array.from({ length: 40 }, (_, i) => [`f${i}`, "x".repeat(100)])),
      eval_count: 1, eval_p50_us: 1, eval_max_us: 1,
    } as const;
    for (let i = 0; i < 19; i++) t.send(big);
    t.flush();
    const total = beacons.reduce((n, b) => n + JSON.parse(b).events.length, 0);
    expect(total).toBe(19);
    expect(beacons.length).toBeGreaterThan(1);
    for (const b of beacons) expect(b.length).toBeLessThanOrEqual(60000);
  });
  it("stop discards the buffer and detaches listeners", () => {
    t.send(ev);
    t.stop();
    window.dispatchEvent(new Event("pagehide"));
    vi.advanceTimersByTime(10000);
    expect(beacons).toHaveLength(0);
  });
});
