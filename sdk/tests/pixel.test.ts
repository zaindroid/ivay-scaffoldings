import { readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { CONTRACTS } from "./helpers";

const SRC = readFileSync(join(__dirname, "..", "pixel", "shopify-custom-pixel.js"), "utf8");
const ajv = new Ajv2020({ allErrors: true, strict: false });
const validate = ajv.compile(JSON.parse(readFileSync(join(CONTRACTS, "event-envelope.schema.json"), "utf8")));

type Handler = (e: unknown) => unknown;
let handlers: Record<string, Handler>;
let posts: Array<{ url: string; init: RequestInit }>;
let cookies: Record<string, string>;

/** Run the pixel the way Shopify does: a script with `analytics`, `browser` and `fetch` in scope. */
function loadPixel() {
  handlers = {};
  const analytics = { subscribe: (name: string, h: Handler) => (handlers[name] = h) };
  const browser = { cookie: { get: async (n: string) => cookies[n] ?? "" } };
  const fetchFn = (url: string, init: RequestInit) => {
    posts.push({ url, init });
    return Promise.resolve({ ok: true });
  };
  new Function("analytics", "browser", "fetch", SRC)(analytics, browser, fetchFn);
}
const flushAsync = () => new Promise((r) => setTimeout(r, 0));
const SID = "a1b2c3d4e5f6a7b8c9d0e1f2";
const checkout = (attrs: Array<{ key: string; value: string }>, amount: number | null = 129.5) => ({
  data: { checkout: { attributes: attrs, totalPrice: amount === null ? null : { amount, currencyCode: "EUR" }, email: "shopper@example.com", shippingAddress: { city: "Bonn" } } },
});

beforeEach(() => {
  posts = [];
  cookies = {};
  loadPixel();
});

describe("checkout pixel", () => {
  it("subscribes to checkout_started and checkout_completed only", () => {
    expect(Object.keys(handlers).sort()).toEqual(["checkout_completed", "checkout_started"]);
  });

  it("checkout_completed posts an order_completed outcome with the total and the session id from the cart attribute", async () => {
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }]));
    await flushAsync();
    expect(posts).toHaveLength(1);
    expect(posts[0].init.keepalive).toBe(true);
    expect(posts[0].init.headers).toBeUndefined();
    const body = JSON.parse(posts[0].init.body as string);
    expect(validate(body), JSON.stringify(validate.errors)).toBe(true);
    expect(body.session_id).toBe(SID);
    expect(body.events).toHaveLength(1);
    expect(body.events[0]).toMatchObject({ type: "outcome", kind: "order_completed", value: 129.5, source: "pixel" });
  });

  it("checkout_started posts a checkout_started outcome", async () => {
    await handlers.checkout_started(checkout([{ key: "ivay_sid", value: SID }], 59));
    await flushAsync();
    const body = JSON.parse(posts[0].init.body as string);
    expect(validate(body)).toBe(true);
    expect(body.events[0]).toMatchObject({ kind: "checkout_started", value: 59, source: "pixel" });
  });

  it("falls back to the ivay_sid cookie when the cart attribute is missing", async () => {
    cookies.ivay_sid = SID;
    await handlers.checkout_completed(checkout([]));
    await flushAsync();
    expect(JSON.parse(posts[0].init.body as string).session_id).toBe(SID);
  });

  it("sends nothing without a session id (no consented SDK session)", async () => {
    await handlers.checkout_completed(checkout([]));
    await handlers.checkout_started(checkout([{ key: "other", value: "x" }]));
    await flushAsync();
    expect(posts).toHaveLength(0);
  });

  it("rejects a malformed session id", async () => {
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: "<script>" }]));
    await flushAsync();
    expect(posts).toHaveLength(0);
  });

  it("event ids are stable per session and kind, so repeats deduplicate server-side", async () => {
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }]));
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }]));
    await flushAsync();
    const ids = posts.map((p) => JSON.parse(p.init.body as string).events[0].event_id);
    expect(ids[0]).toBe(ids[1]);
    expect(ids[0]).toMatch(/^[A-Za-z0-9_-]{8,64}$/);
  });

  it("sends no personal data from the checkout payload", async () => {
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }]));
    await flushAsync();
    const raw = posts[0].init.body as string;
    expect(raw).not.toContain("shopper@example.com");
    expect(raw).not.toContain("Bonn");
  });

  it("a missing total gives value null; a malformed event never throws", async () => {
    await handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }], null));
    await flushAsync();
    expect(JSON.parse(posts[0].init.body as string).events[0].value).toBeNull();
    await expect(handlers.checkout_completed(undefined)).resolves.toBeUndefined();
    await expect(handlers.checkout_started({})).resolves.toBeUndefined();
  });

  it("a failing fetch never throws into checkout", async () => {
    vi.stubGlobal("fetch", undefined);
    handlers = {};
    const analytics = { subscribe: (n: string, h: Handler) => (handlers[n] = h) };
    new Function("analytics", "browser", "fetch", SRC)(analytics, { cookie: { get: async () => "" } }, () => Promise.reject(new Error("offline")));
    await expect(handlers.checkout_completed(checkout([{ key: "ivay_sid", value: SID }]))).resolves.toBeUndefined();
    await flushAsync();
  });
});
