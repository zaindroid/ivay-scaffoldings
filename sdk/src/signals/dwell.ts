import type { SignalCollector, SignalContext } from "../types";

// shipping/returns/size block dwell: seconds the block is at least 50% in view while the tab is
// visible. Elements are found by the configured selectors; only the first match is observed.
const BLOCKS = [
  ["shipping_block_dwell_s", "shipping_block"],
  ["returns_block_dwell_s", "returns_block"],
  ["size_block_dwell_s", "size_block"],
] as const;

interface Block {
  feature: string;
  selector: string;
  ms: number;
  since: number | null;
  inView: boolean;
}

export function dwellCollector(): SignalCollector {
  let blocks: Block[] = [];
  let io: IntersectionObserver | undefined;
  let ticker: ReturnType<typeof setInterval> | undefined;
  let ctx: SignalContext | undefined;
  const els = new Map<Element, Block>();

  const visible = () => document.visibilityState === "visible";
  const sync = () => {
    const now = Date.now();
    for (const b of blocks) {
      const on = b.inView && visible();
      if (on && b.since === null) b.since = now;
      else if (!on && b.since !== null) {
        b.ms += now - b.since;
        b.since = null;
      }
    }
    const any = blocks.some((b) => b.since !== null);
    // While any block is being watched, re-evaluate once a second so a dwell threshold can be crossed.
    if (any && ticker === undefined) ticker = setInterval(() => ctx?.changed(), 1000);
    if (!any && ticker !== undefined) {
      clearInterval(ticker);
      ticker = undefined;
    }
  };
  const observe = () => {
    if (!io || !ctx) return;
    for (const b of blocks) {
      if ([...els.values()].includes(b)) continue;
      try {
        const el = document.querySelector(b.selector);
        if (el) {
          els.set(el, b);
          io.observe(el);
        }
      } catch {
        /* invalid selector: block never observed */
      }
    }
  };
  const onVis = () => {
    sync();
    ctx?.changed();
  };

  return {
    id: "dwell",
    start(c) {
      ctx = c;
      blocks = BLOCKS.map(([feature, key]) => ({
        feature,
        selector: c.config.selectors[key],
        ms: 0,
        since: null,
        inView: false,
      }));
      if (typeof IntersectionObserver === "undefined") return;
      io = new IntersectionObserver(
        (entries) => {
          for (const e of entries) {
            const b = els.get(e.target);
            if (b) b.inView = e.intersectionRatio >= 0.5;
          }
          sync();
          c.changed();
        },
        { threshold: [0, 0.5] },
      );
      observe();
      document.addEventListener("visibilitychange", onVis, { passive: true });
      // Blocks rendered after start (late theme scripts) are picked up once the page has loaded.
      if (document.readyState !== "complete") window.addEventListener("load", observe, { once: true });
    },
    snapshot() {
      const now = Date.now();
      const out: Record<string, number> = {};
      for (const b of blocks) out[b.feature] = Math.floor((b.ms + (b.since === null ? 0 : now - b.since)) / 1000);
      return out;
    },
    stop() {
      io?.disconnect();
      clearInterval(ticker);
      ticker = undefined;
      document.removeEventListener("visibilitychange", onVis);
      window.removeEventListener("load", observe);
      els.clear();
    },
  };
}
