import { readFileSync } from "node:fs";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { initIvay } from "../src/index";
import { shopifyPlatform } from "../src/platform/shopify";
import { fullConfig, mockFetchJson, resetBrowserState } from "./helpers";

const DEMO = join(__dirname, "..", "..", "demo-store");
const ORIGIN = "http://localhost:8080";

/** Load a demo-store page's markup and set the URL, as a browser would show it. */
function loadDemo(file: string, path = "/" + file.replace(/\.html$/, "")) {
  const html = readFileSync(join(DEMO, file), "utf8");
  document.body.innerHTML = /<body[^>]*>([\s\S]*)<\/body>/.exec(html)![1];
  (window as unknown as { happyDOM: { setURL(u: string): void } }).happyDOM.setURL(ORIGIN + path);
}
const setGlobals = (g: Record<string, unknown>) => Object.assign(window, g);
const clearGlobals = () => {
  delete (window as unknown as Record<string, unknown>).Shopify;
  delete (window as unknown as Record<string, unknown>).ShopifyAnalytics;
};

beforeEach(() => {
  resetBrowserState();
  clearGlobals();
  Object.defineProperty(window, "innerWidth", { configurable: true, value: 1280 });
});
afterEach(() => vi.unstubAllGlobals());

describe("default selectors match the demo store markup", () => {
  const sel = fullConfig().selectors;
  it("product page has every block, the size chart trigger, variant inputs and the add-to-cart form", () => {
    loadDemo("products/tee.html", "/products/tee");
    for (const [k, s] of Object.entries(sel)) expect(document.querySelector(s), k).not.toBeNull();
    expect(document.querySelectorAll(sel.variant_selector).length).toBe(4);
  });
  it("cart page has the shipping and returns blocks", () => {
    loadDemo("cart.html", "/cart");
    expect(document.querySelector(sel.shipping_block)).not.toBeNull();
    expect(document.querySelector(sel.returns_block)).not.toBeNull();
  });
});

describe("page context", () => {
  const cfg = fullConfig();
  const ctx = (file: string, path: string, globals: Record<string, unknown> = {}) => {
    clearGlobals();
    loadDemo(file, path);
    setGlobals(globals);
    return shopifyPlatform(cfg).getPageContext();
  };

  it("classifies pages from the URL patterns in the config", () => {
    expect(ctx("products/tee.html", "/products/tee").page_type).toBe("product");
    expect(ctx("cart.html", "/cart").page_type).toBe("cart");
    expect(ctx("policies/shipping-policy.html", "/policies/shipping-policy").page_type).toBe("shipping_policy");
    expect(ctx("policies/refund-policy.html", "/policies/refund-policy").page_type).toBe("returns_policy");
    expect(ctx("index.html", "/").page_type).toBe("other");
    expect(ctx("index.html", "/collections/all").page_type).toBe("other");
  });
  it("the config's patterns override: a shop with /produkte/ URLs", () => {
    loadDemo("products/tee.html", "/produkte/tee");
    const c = { ...cfg, url_patterns: { ...cfg.url_patterns, product: "^/produkte/" } };
    expect(shopifyPlatform(c).getPageContext().page_type).toBe("product");
  });
  it("an invalid pattern in the config never throws and matches nothing", () => {
    loadDemo("products/tee.html", "/products/tee");
    const c = { ...cfg, url_patterns: { ...cfg.url_patterns, product: "(" } };
    expect(shopifyPlatform(c).getPageContext().page_type).toBe("other");
  });
  it("strips the locale prefix from Shopify.routes.root", () => {
    const c = ctx("products/tee.html", "/de/products/tee", { Shopify: { routes: { root: "/de/" } } });
    expect(c.page_type).toBe("product");
  });
  it("product id from ShopifyAnalytics.meta, only on product pages, as a string", () => {
    expect(ctx("products/tee.html", "/products/tee", { ShopifyAnalytics: { meta: { product: { id: 4821 } } } }).product_id).toBe("4821");
    expect(ctx("products/tee.html", "/products/tee", {}).product_id).toBeNull();
    expect(ctx("cart.html", "/cart", { ShopifyAnalytics: { meta: { product: { id: 4821 } } } }).product_id).toBeNull();
  });
  it("country from Shopify.country: uppercase ISO alpha-2 or null", () => {
    clearGlobals();
    expect(ctx("cart.html", "/cart", { Shopify: { country: "DE" } }).country).toBe("DE");
    clearGlobals();
    expect(ctx("cart.html", "/cart", { Shopify: { country: "de" } }).country).toBe("DE");
    clearGlobals();
    expect(ctx("cart.html", "/cart", { Shopify: { country: "Germany" } }).country).toBeNull();
    clearGlobals();
    expect(ctx("cart.html", "/cart", {}).country).toBeNull();
  });
  it("device from viewport width and pointer type", () => {
    const at = (w: number, coarse: boolean) => {
      Object.defineProperty(window, "innerWidth", { configurable: true, value: w });
      vi.stubGlobal("matchMedia", (q: string) => ({ matches: coarse && q.includes("coarse") }));
      loadDemo("cart.html", "/cart");
      return shopifyPlatform(cfg).getPageContext().device;
    };
    expect(at(390, true)).toBe("mobile");
    expect(at(600, false)).toBe("mobile");
    expect(at(1024, true)).toBe("tablet");
    expect(at(1440, false)).toBe("desktop");
  });
});

describe("cart", () => {
  const cfg = fullConfig();
  const cartFetch = (body: unknown, ok = true) => {
    const f = vi.fn(async () => ({ ok, json: async () => body }) as unknown as Response);
    vi.stubGlobal("fetch", f);
    return f;
  };

  it("cart value is total_price in cents divided by 100, from a single /cart.js request", async () => {
    const f = cartFetch({ total_price: 12950, attributes: {} });
    const p = shopifyPlatform(cfg);
    expect((await p.getCart()).value).toBe(129.5);
    expect((await p.getCart()).value).toBe(129.5);
    expect(f).toHaveBeenCalledTimes(1);
    expect(f).toHaveBeenCalledWith("/cart.js", { credentials: "same-origin" });
  });
  it("uses the locale root for both cart endpoints", async () => {
    setGlobals({ Shopify: { routes: { root: "/de/" } } });
    const f = cartFetch({ total_price: 100, attributes: {} });
    const p = shopifyPlatform(cfg);
    await p.getCart();
    await p.setCartAttribute("ivay_sid", "abc");
    expect((f.mock.calls as unknown as string[][]).map((c) => c[0])).toEqual(["/de/cart.js", "/de/cart/update.js"]);
  });
  it("HTTP error, bad JSON and network failure all give a null value, never a throw", async () => {
    cartFetch({}, false);
    expect((await shopifyPlatform(cfg).getCart()).value).toBeNull();
    cartFetch({ total_price: "x" });
    expect((await shopifyPlatform(cfg).getCart()).value).toBeNull();
    vi.stubGlobal("fetch", () => Promise.reject(new Error("offline")));
    expect((await shopifyPlatform(cfg).getCart()).value).toBeNull();
  });
  it("an empty cart is 0, not null", async () => {
    cartFetch({ total_price: 0, attributes: {} });
    expect((await shopifyPlatform(cfg).getCart()).value).toBe(0);
  });

  it("setCartAttribute posts to /cart/update.js when the attribute is missing or different", async () => {
    const f = cartFetch({ total_price: 0, attributes: { other: "x" } });
    await shopifyPlatform(cfg).setCartAttribute("ivay_sid", "sess123456");
    expect(f).toHaveBeenCalledTimes(2);
    const [url, init] = f.mock.calls[1] as unknown as [string, RequestInit];
    expect(url).toBe("/cart/update.js");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({ attributes: { ivay_sid: "sess123456" } });
  });
  it("setCartAttribute does not write when the attribute is already correct", async () => {
    const f = cartFetch({ total_price: 0, attributes: { ivay_sid: "sess123456" } });
    await shopifyPlatform(cfg).setCartAttribute("ivay_sid", "sess123456");
    expect(f).toHaveBeenCalledTimes(1); // only the read
  });
  it("setCartAttribute does not write when the cart could not be read", async () => {
    const f = cartFetch({}, false);
    await shopifyPlatform(cfg).setCartAttribute("ivay_sid", "sess123456");
    expect(f).toHaveBeenCalledTimes(1);
  });
  it("setCartAttribute swallows a failed write", async () => {
    let n = 0;
    vi.stubGlobal("fetch", async () => {
      if (n++ === 0) return { ok: true, json: async () => ({ attributes: {} }) };
      throw new Error("blocked");
    });
    await expect(shopifyPlatform(cfg).setCartAttribute("ivay_sid", "s")).resolves.toBeUndefined();
  });
});

describe("add-to-cart detection", () => {
  it("fires on submit of the add-to-cart form, not on other forms, and does not touch fetch", () => {
    const realFetch = globalThis.fetch;
    const realXhr = window.XMLHttpRequest;
    loadDemo("products/tee.html", "/products/tee");
    const cb = vi.fn();
    shopifyPlatform(fullConfig()).onAddToCart(cb);
    document.getElementById("product-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(cb).toHaveBeenCalledTimes(1);
    expect(globalThis.fetch).toBe(realFetch);
    expect(window.XMLHttpRequest).toBe(realXhr);

    loadDemo("cart.html", "/cart");
    document.querySelector("form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(cb).toHaveBeenCalledTimes(1);
  });
  it("a theme that calls preventDefault on submit is still detected (capture phase)", () => {
    loadDemo("products/tee.html", "/products/tee");
    const cb = vi.fn();
    shopifyPlatform(fullConfig()).onAddToCart(cb);
    const form = document.getElementById("product-form")!;
    form.addEventListener("submit", (e) => e.preventDefault());
    form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    expect(cb).toHaveBeenCalledTimes(1);
  });
});

describe("through initIvay with the shopify adapter", () => {
  let beacons: string[];
  let handle: { stop(): void } | undefined;
  beforeEach(() => {
    beacons = [];
    Object.defineProperty(navigator, "sendBeacon", { configurable: true, value: (_u: string, b: string) => (beacons.push(b), true) });
  });
  afterEach(() => handle?.stop());

  function stubNetwork(cart: { total_price: number; attributes: Record<string, string> }) {
    const calls: string[] = [];
    vi.stubGlobal("fetch", async (url: string, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url.endsWith("shop_dev.json")) return { ok: true, json: async () => fullConfig() };
      if (url === "/cart.js") return { ok: true, json: async () => cart };
      return { ok: true, json: async () => ({}) };
    });
    return calls;
  }
  const events = () => beacons.flatMap((b) => JSON.parse(b).events as Array<Record<string, unknown>>);

  it("with consent: page_view, cart value in the summary, cart attribute, add-to-cart outcome", async () => {
    loadDemo("products/tee.html", "/products/tee");
    setGlobals({ Shopify: { country: "DE" }, ShopifyAnalytics: { meta: { product: { id: 4821 } } } });
    const calls = stubNetwork({ total_price: 2900, attributes: {} });
    handle = initIvay({ shopId: "shop_dev", configBase: "http://static/config", consent: { provider: "custom", isGranted: () => true }, platform: "shopify" });
    await vi.waitFor(() => expect(calls).toContain("POST /cart/update.js"));
    document.getElementById("product-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    window.dispatchEvent(new Event("pagehide"));
    const sid = /ivay_sid=([0-9a-f]+)/.exec(document.cookie)![1];
    expect(calls.filter((c) => c.startsWith("GET /cart.js"))).toHaveLength(1);
    const ev = events();
    expect(ev.find((e) => e.type === "page_view")).toMatchObject({ page_type: "product", product_id: "4821", country: "DE" });
    expect(ev.find((e) => e.type === "outcome")).toMatchObject({ kind: "add_to_cart", source: "sdk", value: null });
    const summary = ev.find((e) => e.type === "page_summary") as { features: Record<string, unknown> };
    expect(summary.features.cart_value).toBe(29);
    expect(sid).toHaveLength(24);
  });

  it("without consent: no cart request, no cart write, no listeners that send", async () => {
    loadDemo("products/tee.html", "/products/tee");
    const calls = stubNetwork({ total_price: 2900, attributes: {} });
    handle = initIvay({ shopId: "shop_dev", configBase: "http://static/config", consent: { provider: "custom", isGranted: () => false }, platform: "shopify" });
    await new Promise((r) => setTimeout(r, 30));
    document.getElementById("product-form")!.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
    window.dispatchEvent(new Event("pagehide"));
    expect(calls).toEqual([]);
    expect(beacons).toHaveLength(0);
    expect(document.cookie).toBe("");
  });
});

void mockFetchJson;
