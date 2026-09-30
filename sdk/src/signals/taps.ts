import type { SignalCollector } from "../types";

// repeated_taps_5s: the most taps on any one element within 5 s. Elements are tracked in a
// WeakMap; no selector, text or attribute is kept.
const WINDOW_MS = 5000;

export function tapsCollector(): SignalCollector {
  const taps = new WeakMap<EventTarget, number[]>();
  let max = 0;
  let onClick: ((e: Event) => void) | undefined;
  return {
    id: "taps",
    start(ctx) {
      onClick = (e) => {
        if (!e.target) return;
        const now = Date.now();
        const list = (taps.get(e.target) ?? []).filter((t) => now - t <= WINDOW_MS);
        list.push(now);
        taps.set(e.target, list);
        if (list.length > max) {
          max = list.length;
          ctx.changed();
        }
      };
      document.addEventListener("click", onClick, { capture: true, passive: true });
    },
    snapshot: () => ({ repeated_taps_5s: max }),
    stop() {
      if (onClick) document.removeEventListener("click", onClick, { capture: true });
    },
  };
}
