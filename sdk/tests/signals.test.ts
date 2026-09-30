import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { createFeatures } from "../src/features";
import { defaultCollectors } from "../src/signals/registry";
import { dwellCollector } from "../src/signals/dwell";
import { scrollCollector } from "../src/signals/scroll";
import { sessionCollector } from "../src/signals/session";
import { tapsCollector } from "../src/signals/taps";
import { variantsCollector } from "../src/signals/variants";
import { resetBrowserState } from "./helpers";
import { MockIO, installIO, makeCtx, setScrollY, setVisibility } from "./signals.helpers";

beforeEach(() => {
  vi.useFakeTimers();
  resetBrowserState();
  document.body.innerHTML = "";
  setVisibility("visible");
  setScrollY(0);
  installIO();
});
afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

const block = (name: string) => {
  const el = document.createElement("div");
  el.setAttribute("data-ivay-block", name);
  document.body.appendChild(el);
  return el;
};

describe("dwell", () => {
  it("counts seconds while the block is at least 50% in view", () => {
    const el = block("shipping");
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    expect(c.snapshot()).toEqual({ shipping_block_dwell_s: 0, returns_block_dwell_s: 0, size_block_dwell_s: 0 });
    MockIO.instances[0].report(el, 0.6);
    vi.advanceTimersByTime(40_000);
    expect(c.snapshot().shipping_block_dwell_s).toBe(40);
    c.stop();
  });

  it("does not count a block that is less than 50% in view", () => {
    const el = block("shipping");
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    MockIO.instances[0].report(el, 0.49);
    vi.advanceTimersByTime(60_000);
    expect(c.snapshot().shipping_block_dwell_s).toBe(0);
    c.stop();
  });

  it("pauses when the block scrolls out of view and resumes on return", () => {
    const el = block("shipping");
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    const io = MockIO.instances[0];
    io.report(el, 1);
    vi.advanceTimersByTime(10_000);
    io.report(el, 0.1);
    vi.advanceTimersByTime(30_000);
    expect(c.snapshot().shipping_block_dwell_s).toBe(10);
    io.report(el, 0.8);
    vi.advanceTimersByTime(5_000);
    expect(c.snapshot().shipping_block_dwell_s).toBe(15);
    c.stop();
  });

  it("pauses while the tab is hidden and resumes when visible", () => {
    const el = block("size");
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    MockIO.instances[0].report(el, 1);
    vi.advanceTimersByTime(7_000);
    setVisibility("hidden");
    vi.advanceTimersByTime(60_000);
    expect(c.snapshot().size_block_dwell_s).toBe(7);
    setVisibility("visible");
    vi.advanceTimersByTime(3_000);
    expect(c.snapshot().size_block_dwell_s).toBe(10);
    c.stop();
  });

  it("tracks the three blocks independently", () => {
    const a = block("shipping");
    const b = block("returns");
    block("size");
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    const io = MockIO.instances[0];
    io.report(a, 1);
    vi.advanceTimersByTime(4_000);
    io.report(b, 1);
    vi.advanceTimersByTime(2_000);
    expect(c.snapshot()).toEqual({ shipping_block_dwell_s: 6, returns_block_dwell_s: 2, size_block_dwell_s: 0 });
    c.stop();
  });

  it("asks for re-evaluation every second while a block is being watched, and stops when not", () => {
    const el = block("shipping");
    const { ctx, changed } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    const io = MockIO.instances[0];
    io.report(el, 1);
    changed.mockClear();
    vi.advanceTimersByTime(3_000);
    expect(changed).toHaveBeenCalledTimes(3);
    io.report(el, 0);
    changed.mockClear();
    vi.advanceTimersByTime(5_000);
    expect(changed).not.toHaveBeenCalled();
    c.stop();
  });

  it("missing block, invalid selector and missing IntersectionObserver are all harmless", () => {
    const { ctx } = makeCtx();
    ctx.config.selectors.shipping_block = "[[[";
    const c = dwellCollector();
    expect(() => c.start(ctx)).not.toThrow();
    expect(c.snapshot().shipping_block_dwell_s).toBe(0);
    c.stop();
    vi.stubGlobal("IntersectionObserver", undefined);
    const c2 = dwellCollector();
    c2.start(makeCtx().ctx);
    expect(c2.snapshot().shipping_block_dwell_s).toBe(0);
  });

  it("observes a block that appears after start once the page has loaded", () => {
    Object.defineProperty(document, "readyState", { configurable: true, value: "interactive" });
    const { ctx } = makeCtx();
    const c = dwellCollector();
    c.start(ctx);
    expect(MockIO.instances[0].observed.size).toBe(0);
    const el = block("shipping");
    window.dispatchEvent(new Event("load"));
    expect(MockIO.instances[0].observed.has(el)).toBe(true);
    Object.defineProperty(document, "readyState", { configurable: true, value: "complete" });
    c.stop();
  });
});

describe("scroll_reversals_30s", () => {
  it("counts a down-to-up change of at least 50 px", () => {
    const c = scrollCollector();
    c.start(makeCtx().ctx);
    setScrollY(100);
    setScrollY(400);
    setScrollY(340);
    expect(c.snapshot().scroll_reversals_30s).toBe(1);
    c.stop();
  });
  it("ignores wobble under 50 px and does not count up-to-down", () => {
    const c = scrollCollector();
    c.start(makeCtx().ctx);
    setScrollY(400);
    setScrollY(360); // -40: not a reversal
    setScrollY(500);
    expect(c.snapshot().scroll_reversals_30s).toBe(0);
    setScrollY(440); // -60: reversal 1
    setScrollY(300);
    setScrollY(360); // +60 up-to-down: not counted
    expect(c.snapshot().scroll_reversals_30s).toBe(1);
    c.stop();
  });
  it("counts repeated reversals and forgets them after 30 s", () => {
    const c = scrollCollector();
    c.start(makeCtx().ctx);
    for (const y of [300, 200, 300, 200]) setScrollY(y);
    expect(c.snapshot().scroll_reversals_30s).toBe(2);
    vi.advanceTimersByTime(29_000);
    expect(c.snapshot().scroll_reversals_30s).toBe(2);
    vi.advanceTimersByTime(2_000);
    expect(c.snapshot().scroll_reversals_30s).toBe(0);
    c.stop();
  });
  it("uses passive listeners", () => {
    const spy = vi.spyOn(window, "addEventListener");
    const c = scrollCollector();
    c.start(makeCtx().ctx);
    expect(spy).toHaveBeenCalledWith("scroll", expect.any(Function), { passive: true });
    c.stop();
  });
});

describe("variant_toggles_since_atc", () => {
  const variantInput = () => {
    document.body.innerHTML =
      "<form action='/cart/add'><input name='id' id='v'></form><input id='other'>";
    return document.getElementById("v")!;
  };
  it("counts variant changes and ignores unrelated inputs", () => {
    const v = variantInput();
    const c = variantsCollector();
    c.start(makeCtx().ctx);
    v.dispatchEvent(new Event("change", { bubbles: true }));
    v.dispatchEvent(new Event("change", { bubbles: true }));
    document.getElementById("other")!.dispatchEvent(new Event("change", { bubbles: true }));
    expect(c.snapshot().variant_toggles_since_atc).toBe(2);
    c.stop();
  });
  it("resets on add-to-cart", () => {
    const v = variantInput();
    const m = makeCtx();
    const c = variantsCollector();
    c.start(m.ctx);
    v.dispatchEvent(new Event("change", { bubbles: true }));
    m.fireAddToCart();
    expect(c.snapshot().variant_toggles_since_atc).toBe(0);
    v.dispatchEvent(new Event("change", { bubbles: true }));
    expect(c.snapshot().variant_toggles_since_atc).toBe(1);
    c.stop();
  });
});

describe("repeated_taps_5s", () => {
  it("is the most taps on one element inside 5 s", () => {
    document.body.innerHTML = "<button id='a'></button><button id='b'></button>";
    const a = document.getElementById("a")!;
    const b = document.getElementById("b")!;
    const c = tapsCollector();
    c.start(makeCtx().ctx);
    for (let i = 0; i < 4; i++) a.click();
    b.click();
    expect(c.snapshot().repeated_taps_5s).toBe(4);
    c.stop();
  });
  it("does not accumulate taps spread more than 5 s apart", () => {
    document.body.innerHTML = "<button id='a'></button>";
    const a = document.getElementById("a")!;
    const c = tapsCollector();
    c.start(makeCtx().ctx);
    for (let i = 0; i < 5; i++) {
      a.click();
      vi.advanceTimersByTime(6_000);
    }
    expect(c.snapshot().repeated_taps_5s).toBe(1);
    c.stop();
  });
  it("keeps no selector or text: the snapshot is one number", () => {
    document.body.innerHTML = "<button id='secret-email'>jane@example.com</button>";
    const c = tapsCollector();
    c.start(makeCtx().ctx);
    document.getElementById("secret-email")!.click();
    expect(JSON.stringify(c.snapshot())).toBe('{"repeated_taps_5s":1}');
    c.stop();
  });
});

describe("session-scoped features", () => {
  it("defaults, then counts pages, size chart opens, hidden tabs and cart adds", () => {
    document.body.innerHTML = "<a data-ivay='size-chart' id='sc'>Size guide</a>";
    const m = makeCtx();
    const c = sessionCollector();
    c.start(m.ctx);
    expect(c.snapshot()).toEqual({
      shipping_page_visited: false, returns_page_visited: false, size_chart_opens: 0,
      tab_hidden_count: 0, pages_viewed: 1, cart_adds: 0,
    });
    document.getElementById("sc")!.click();
    document.getElementById("sc")!.click();
    setVisibility("hidden");
    setVisibility("visible");
    m.fireAddToCart();
    const s = c.snapshot();
    expect(s.size_chart_opens).toBe(2);
    expect(s.tab_hidden_count).toBe(1);
    expect(s.cart_adds).toBe(1);
    c.stop();
  });
  it("marks shipping and returns policy visits", () => {
    const c1 = sessionCollector();
    c1.start(makeCtx("shipping_policy", "sid-a").ctx);
    expect(c1.snapshot().shipping_page_visited).toBe(true);
    expect(c1.snapshot().returns_page_visited).toBe(false);
    const c2 = sessionCollector();
    c2.start(makeCtx("returns_policy", "sid-b").ctx);
    expect(c2.snapshot().returns_page_visited).toBe(true);
    c1.stop();
    c2.stop();
  });
  it("survives a simulated navigation: new page, same session", () => {
    const page1 = makeCtx("shipping_policy", "sid-nav");
    const c1 = sessionCollector();
    c1.start(page1.ctx);
    page1.fireAddToCart();
    c1.stop(); // page unloads; new page load builds everything again from sessionStorage
    const page2 = makeCtx("product", "sid-nav");
    const c2 = sessionCollector();
    c2.start(page2.ctx);
    const s = c2.snapshot();
    expect(s.shipping_page_visited).toBe(true);
    expect(s.pages_viewed).toBe(2);
    expect(s.cart_adds).toBe(1);
    c2.stop();
  });
  it("a new session starts from zero", () => {
    const c1 = sessionCollector();
    c1.start(makeCtx("shipping_policy", "sid-old").ctx);
    c1.stop();
    const c2 = sessionCollector();
    c2.start(makeCtx("product", "sid-new").ctx);
    expect(c2.snapshot().shipping_page_visited).toBe(false);
    expect(c2.snapshot().pages_viewed).toBe(1);
    c2.stop();
  });
  it("page-scoped dwell resets on navigation while session features persist", () => {
    const el = block("shipping");
    const m1 = makeCtx("product", "sid-mix");
    const cs1 = defaultCollectors();
    const f1 = createFeatures(m1.ctx, cs1, () => {});
    f1.start();
    MockIO.instances[0].report(el, 1);
    vi.advanceTimersByTime(12_000);
    expect(f1.snapshot().shipping_block_dwell_s).toBe(12);
    f1.stop();
    const f2 = createFeatures(makeCtx("product", "sid-mix").ctx, defaultCollectors(), () => {});
    f2.start();
    expect(f2.snapshot().shipping_block_dwell_s).toBe(0);
    expect(f2.snapshot().pages_viewed).toBe(2);
    f2.stop();
  });
});

describe("features assembly", () => {
  it("merges context and every collector into one snapshot", () => {
    const f = createFeatures(makeCtx().ctx, defaultCollectors(), () => {});
    f.start();
    const s = f.snapshot();
    for (const k of [
      "page_type", "device", "cart_value", "shipping_block_dwell_s", "returns_block_dwell_s",
      "size_block_dwell_s", "scroll_reversals_30s", "variant_toggles_since_atc", "repeated_taps_5s",
      "shipping_page_visited", "returns_page_visited", "size_chart_opens", "tab_hidden_count",
      "pages_viewed", "cart_adds",
    ]) expect(s, k).toHaveProperty(k);
    expect(s.cart_value).toBeNull();
    expect(Object.keys(s).length).toBeLessThanOrEqual(40);
    f.stop();
  });
  it("only scalar or null values (nothing nested, nothing textual beyond enums)", () => {
    const f = createFeatures(makeCtx().ctx, defaultCollectors(), () => {});
    f.start();
    for (const v of Object.values(f.snapshot())) expect(["boolean", "number", "string"].includes(typeof v) || v === null).toBe(true);
    f.stop();
  });
  it("throttles updates to one per 100 ms, with a trailing update", () => {
    const seen: number[] = [];
    let n = 0;
    const collector = {
      id: "t",
      start: (c: { changed(): void }) => (fire = c.changed),
      snapshot: () => ({ n }),
      stop: () => {},
    };
    let fire: () => void = () => {};
    const f = createFeatures(makeCtx().ctx, [collector], (x) => seen.push(x.n as number));
    f.start();
    expect(seen).toEqual([0]); // immediate first update
    n = 1; fire();
    n = 2; fire();
    n = 3; fire();
    expect(seen).toEqual([0]); // within 100 ms: held back
    vi.advanceTimersByTime(100);
    expect(seen).toEqual([0, 3]); // one trailing update with the latest value
    vi.advanceTimersByTime(1000);
    expect(seen).toHaveLength(2);
    f.stop();
  });
  it("setContext adds cart_value", () => {
    const f = createFeatures(makeCtx().ctx, [], () => {});
    f.start();
    f.setContext({ cart_value: 129.5 });
    expect(f.snapshot().cart_value).toBe(129.5);
    f.stop();
  });
  it("stop stops every collector", () => {
    const stop = vi.fn();
    const f = createFeatures(makeCtx().ctx, [{ id: "x", start() {}, snapshot: () => ({}), stop }], () => {});
    f.start();
    f.stop();
    expect(stop).toHaveBeenCalledTimes(1);
  });
});
