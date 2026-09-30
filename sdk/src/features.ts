import type { Features, SignalCollector, SignalContext } from "./types";

const THROTTLE_MS = 100;

export interface FeatureSet {
  start(): void;
  /** Collector snapshots plus page context (page_type, device, cart_value). */
  snapshot(): Features;
  /** Late-arriving context such as cart_value. */
  setContext(c: Features): void;
  stop(): void;
}

/**
 * Assembles Features from the collectors. Collectors call `changed()`; `onUpdate` runs at
 * most once per 100 ms (leading edge, plus one trailing call if more changes arrived).
 */
export function createFeatures(
  base: Omit<SignalContext, "changed">,
  collectors: SignalCollector[],
  onUpdate: (f: Features) => void,
): FeatureSet {
  const context: Features = { page_type: base.page.page_type, device: base.page.device, cart_value: null };
  let last = -Infinity;
  let timer: ReturnType<typeof setTimeout> | undefined;

  const snapshot = (): Features => {
    const out: Features = { ...context };
    for (const c of collectors) Object.assign(out, c.snapshot());
    return out;
  };
  const run = () => {
    timer = undefined;
    last = Date.now();
    onUpdate(snapshot());
  };
  const changed = () => {
    const wait = THROTTLE_MS - (Date.now() - last);
    if (wait <= 0 && timer === undefined) run();
    else {
      if (timer === undefined) timer = setTimeout(run, Math.max(wait, 0));
    }
  };

  return {
    start() {
      for (const c of collectors) c.start({ ...base, changed });
      changed();
    },
    snapshot,
    setContext(c) {
      Object.assign(context, c);
      changed();
    },
    stop() {
      clearTimeout(timer);
      for (const c of collectors) c.stop();
    },
  };
}
