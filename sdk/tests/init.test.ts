import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initIvay } from "../src/index";
import type { InitOptions, PlatformAdapter } from "../src/types";
import { fullConfig, mockFetchJson, resetBrowserState } from "./helpers";

let beacons: string[];
let handle: { stop(): void } | undefined;

const platform: PlatformAdapter = {
  getPageContext: () => ({ page_type: "product", device: "desktop", product_id: "4821", country: "DE" }),
  getCart: async () => ({ value: null }),
  onAddToCart: () => {},
  setCartAttribute: () => {},
};

function opts(granted: (p: string[]) => boolean, onChange?: (cb: () => void) => void): InitOptions {
  return {
    shopId: "shop_dev",
    configBase: "http://static/config",
    consent: { provider: "custom", isGranted: granted, onChange },
    platform,
  };
}
const storageEmpty = () => document.cookie === "" && sessionStorage.length === 0 && localStorage.length === 0;

beforeEach(() => {
  resetBrowserState();
  beacons = [];
  Object.defineProperty(navigator, "sendBeacon", {
    configurable: true,
    value: (_u: string, b: string) => (beacons.push(b), true),
  });
});
afterEach(() => {
  handle?.stop();
  vi.unstubAllGlobals();
});

describe("consent gating", () => {
  it("without consent: no fetch, no storage, nothing sent", async () => {
    const f = mockFetchJson(fullConfig());
    handle = initIvay(opts(() => false, () => {}));
    await new Promise((r) => setTimeout(r, 20));
    window.dispatchEvent(new Event("pagehide"));
    expect(f).not.toHaveBeenCalled();
    expect(storageEmpty()).toBe(true);
    expect(beacons).toHaveLength(0);
  });

  it("consent arriving later starts the SDK", async () => {
    const f = mockFetchJson(fullConfig());
    let granted = false;
    let fire: () => void = () => {};
    handle = initIvay(opts(() => granted, (cb) => (fire = cb)));
    await new Promise((r) => setTimeout(r, 10));
    expect(f).not.toHaveBeenCalled();
    expect(storageEmpty()).toBe(true);

    granted = true;
    fire();
    await vi.waitFor(() => expect(document.cookie).toContain("ivay_vid="));
    expect(f).toHaveBeenCalledWith("http://static/config/shop_dev.json", expect.anything());
    expect(document.cookie).toContain("ivay_sid=");
    window.dispatchEvent(new Event("pagehide"));
    expect(beacons).toHaveLength(1);
    const b = JSON.parse(beacons[0]);
    expect(b.events[0].type).toBe("page_view");
    expect(b.visitor_hash).toMatch(/^[0-9a-f]{64}$/);
  });

  it("starting twice on repeated consent events fetches config once", async () => {
    const f = mockFetchJson(fullConfig());
    let fire: () => void = () => {};
    handle = initIvay(opts(() => true, (cb) => (fire = cb)));
    fire();
    fire();
    await vi.waitFor(() => expect(document.cookie).toContain("ivay_sid="));
    expect(f).toHaveBeenCalledTimes(1);
  });

  it("the raw visitor id is never sent", async () => {
    mockFetchJson(fullConfig());
    handle = initIvay(opts(() => true));
    await vi.waitFor(() => expect(document.cookie).toMatch(/ivay_vid=[0-9a-f]{32}/));
    const vid = /ivay_vid=([0-9a-f]+)/.exec(document.cookie)![1];
    window.dispatchEvent(new Event("pagehide"));
    expect(beacons.join("")).not.toContain(vid);
  });

  it("config requiring more consent than init purposes stays inert until granted", async () => {
    const cfg = { ...fullConfig(), required_consent: ["analytics", "marketing"] };
    mockFetchJson(cfg);
    const seen: string[][] = [];
    handle = initIvay(opts((p) => (seen.push(p), !p.includes("marketing"))));
    await vi.waitFor(() => expect(seen.some((p) => p.includes("marketing"))).toBe(true));
    await new Promise((r) => setTimeout(r, 20));
    expect(storageEmpty()).toBe(true);
    expect(beacons).toHaveLength(0);
  });
});

describe("inert states", () => {
  it("a failed config fetch (network error) leaves the SDK inert", async () => {
    vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
    handle = initIvay(opts(() => true));
    await new Promise((r) => setTimeout(r, 20));
    window.dispatchEvent(new Event("pagehide"));
    expect(storageEmpty()).toBe(true);
    expect(beacons).toHaveLength(0);
  });
  it("HTTP error, invalid JSON shape and kill switch are all inert", async () => {
    for (const cfg of [
      [{}, false],
      [{ ...fullConfig(), mode: "banana" }, true],
      [{ ...fullConfig(), kill_switch: true }, true],
    ] as const) {
      resetBrowserState();
      mockFetchJson(cfg[0], cfg[1]);
      const h = initIvay(opts(() => true));
      await new Promise((r) => setTimeout(r, 20));
      window.dispatchEvent(new Event("pagehide"));
      expect(storageEmpty()).toBe(true);
      expect(beacons).toHaveLength(0);
      h.stop();
    }
  });
  it("a throwing consent provider never throws to the host", () => {
    mockFetchJson(fullConfig());
    expect(() => {
      handle = initIvay(opts(() => { throw new Error("cmp broke"); }));
    }).not.toThrow();
  });
});

describe("collectors start after consent", () => {
  it("session features are written only after consent and persist across a simulated navigation", async () => {
    mockFetchJson(fullConfig());
    let granted = false;
    let fire: () => void = () => {};
    handle = initIvay(opts(() => granted, (cb) => (fire = cb)));
    await new Promise((r) => setTimeout(r, 10));
    expect(sessionStorage.length).toBe(0);
    granted = true;
    fire();
    await vi.waitFor(() => expect(sessionStorage.getItem("ivay_s")).toContain("pages_viewed"));
    handle.stop();
    // "navigate": same cookies and sessionStorage, fresh SDK instance
    handle = initIvay(opts(() => true));
    await vi.waitFor(() => expect(JSON.parse(sessionStorage.getItem("ivay_s")!).features.pages_viewed).toBe(2));
  });
  it("add-to-cart from the platform reaches the session counter", async () => {
    mockFetchJson(fullConfig());
    let atc: () => void = () => {};
    const p = { ...platform, onAddToCart: (cb: () => void) => (atc = cb) };
    handle = initIvay({ ...opts(() => true), platform: p });
    await vi.waitFor(() => expect(sessionStorage.getItem("ivay_s")).toContain("pages_viewed"));
    atc();
    expect(JSON.parse(sessionStorage.getItem("ivay_s")!).features.cart_adds).toBe(1);
  });
});

describe("stop during start-up", () => {
  it("stop() while the config is in flight creates nothing afterwards", async () => {
    let resolve!: (v: unknown) => void;
    vi.stubGlobal("fetch", () => new Promise((r) => (resolve = r)));
    const h = initIvay(opts(() => true));
    h.stop();
    resolve({ ok: true, json: async () => fullConfig() });
    await new Promise((r) => setTimeout(r, 30));
    window.dispatchEvent(new Event("pagehide"));
    expect(storageEmpty()).toBe(true);
    expect(beacons).toHaveLength(0);
  });
});
