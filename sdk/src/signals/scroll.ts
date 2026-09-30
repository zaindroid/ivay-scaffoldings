import type { SignalCollector } from "../types";

// scroll_reversals_30s: direction changes from down to up of at least 50 px, in the last 30 s.
const MIN_PX = 50;
const WINDOW_MS = 30000;

export function scrollCollector(): SignalCollector {
  let times: number[] = [];
  let dir: "down" | "up" = "down";
  let extreme = 0; // peak while going down, trough while going up
  let onScroll: (() => void) | undefined;

  return {
    id: "scroll",
    start(ctx) {
      extreme = window.scrollY;
      onScroll = () => {
        const y = window.scrollY;
        if (dir === "down") {
          if (y > extreme) extreme = y;
          else if (extreme - y >= MIN_PX) {
            times.push(Date.now());
            dir = "up";
            extreme = y;
            ctx.changed();
          }
        } else if (y < extreme) extreme = y;
        else if (y - extreme >= MIN_PX) {
          dir = "down";
          extreme = y;
        }
      };
      window.addEventListener("scroll", onScroll, { passive: true });
    },
    snapshot() {
      const cutoff = Date.now() - WINDOW_MS;
      times = times.filter((t) => t > cutoff);
      return { scroll_reversals_30s: times.length };
    },
    stop() {
      if (onScroll) window.removeEventListener("scroll", onScroll);
    },
  };
}
