import type { SignalCollector } from "../types";
import { matches } from "./variants";

// Session-scoped features live in the session store so they survive page navigation.
const DEFAULTS = {
  shipping_page_visited: false,
  returns_page_visited: false,
  size_chart_opens: 0,
  tab_hidden_count: 0,
  pages_viewed: 0,
  cart_adds: 0,
} as const;

export function sessionCollector(): SignalCollector {
  let store: import("../types").SessionStore | undefined;
  let onClick: ((e: Event) => void) | undefined;
  let onVis: (() => void) | undefined;

  const bump = (key: "size_chart_opens" | "tab_hidden_count" | "pages_viewed" | "cart_adds") =>
    store?.update((s) => {
      s.features[key] = ((s.features[key] as number | undefined) ?? 0) + 1;
    });

  return {
    id: "session",
    start(ctx) {
      store = ctx.session;
      bump("pages_viewed");
      const pt = ctx.page.page_type;
      if (pt === "shipping_policy" || pt === "returns_policy") {
        const key = pt === "shipping_policy" ? "shipping_page_visited" : "returns_page_visited";
        store.update((s) => {
          s.features[key] = true;
        });
      }
      const sel = ctx.config.selectors.size_chart_trigger;
      onClick = (e) => {
        if (matches(e.target, sel)) {
          bump("size_chart_opens");
          ctx.changed();
        }
      };
      document.addEventListener("click", onClick, { capture: true, passive: true });
      onVis = () => {
        if (document.visibilityState === "hidden") bump("tab_hidden_count");
      };
      document.addEventListener("visibilitychange", onVis, { passive: true });
      ctx.onAddToCart(() => {
        bump("cart_adds");
        ctx.changed();
      });
    },
    snapshot() {
      const f = store?.get().features ?? {};
      return Object.fromEntries(
        Object.entries(DEFAULTS).map(([k, d]) => [k, (f[k] as number | boolean | undefined) ?? d]),
      );
    },
    stop() {
      if (onClick) document.removeEventListener("click", onClick, { capture: true });
      if (onVis) document.removeEventListener("visibilitychange", onVis);
    },
  };
}
