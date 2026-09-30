import { vi } from "vitest";
import { createSessionStore } from "../src/session-store";
import type { PageType, SignalContext } from "../src/types";
import { fullConfig } from "./helpers";

type IOCallback = (entries: Array<Partial<IntersectionObserverEntry>>) => void;

export class MockIO {
  static instances: MockIO[] = [];
  observed = new Set<Element>();
  constructor(
    private cb: IOCallback,
    public options?: IntersectionObserverInit,
  ) {
    MockIO.instances.push(this);
  }
  observe(el: Element) {
    this.observed.add(el);
  }
  unobserve(el: Element) {
    this.observed.delete(el);
  }
  disconnect() {
    this.observed.clear();
  }
  /** Simulate the browser reporting a new visible ratio for an element. */
  report(el: Element, ratio: number) {
    this.cb([{ target: el, intersectionRatio: ratio, isIntersecting: ratio > 0 }]);
  }
}

export function installIO() {
  MockIO.instances = [];
  vi.stubGlobal("IntersectionObserver", MockIO);
}

export function setVisibility(state: "visible" | "hidden") {
  Object.defineProperty(document, "visibilityState", { configurable: true, value: state });
  document.dispatchEvent(new Event("visibilitychange"));
}

export function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", { configurable: true, value: y });
  window.dispatchEvent(new Event("scroll"));
}

export function makeCtx(page_type: PageType = "product", sid = "sid-test-1") {
  const addToCart: Array<() => void> = [];
  const changed = vi.fn();
  const session = createSessionStore(sid);
  const ctx: SignalContext = {
    config: fullConfig(),
    page: { page_type, device: "desktop", product_id: "4821", country: "DE" },
    changed,
    session,
    onAddToCart: (cb) => addToCart.push(cb),
  };
  return { ctx, changed, session, addToCart, fireAddToCart: () => addToCart.forEach((f) => f()) };
}
