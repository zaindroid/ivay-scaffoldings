import type { SignalCollector } from "../types";

export const matches = (t: EventTarget | null, selector: string): boolean => {
  try {
    return t instanceof Element && t.closest(selector) !== null;
  } catch {
    return false; // invalid selector
  }
};

// variant_toggles_since_atc: variant changes since the last add-to-cart. Counts events only.
export function variantsCollector(): SignalCollector {
  let n = 0;
  let onChange: ((e: Event) => void) | undefined;
  return {
    id: "variants",
    start(ctx) {
      const sel = ctx.config.selectors.variant_selector;
      onChange = (e) => {
        if (matches(e.target, sel)) {
          n++;
          ctx.changed();
        }
      };
      document.addEventListener("change", onChange, { passive: true });
      ctx.onAddToCart(() => {
        n = 0;
        ctx.changed();
      });
    },
    snapshot: () => ({ variant_toggles_since_atc: n }),
    stop() {
      if (onChange) document.removeEventListener("change", onChange);
    },
  };
}
