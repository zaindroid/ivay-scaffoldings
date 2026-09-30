// Every entry point goes through the guard: errors never reach the host page, and after
// `limit` caught errors the SDK disables itself.

export interface Guard {
  wrap<A extends unknown[]>(fn: (...a: A) => unknown): (...a: A) => void;
  isDisabled(): boolean;
}

export function createGuard(onDisable: () => void, limit = 5): Guard {
  let errors = 0;
  let disabled = false;
  const fail = () => {
    if (++errors >= limit && !disabled) {
      disabled = true;
      try {
        onDisable();
      } catch {
        /* nothing more to do */
      }
    }
  };
  return {
    isDisabled: () => disabled,
    wrap:
      (fn) =>
      (...a) => {
        if (disabled) return;
        try {
          const r = fn(...a);
          if (r && typeof (r as Promise<unknown>).then === "function") {
            (r as Promise<unknown>).then(undefined, fail);
          }
        } catch {
          fail();
        }
      },
  };
}
