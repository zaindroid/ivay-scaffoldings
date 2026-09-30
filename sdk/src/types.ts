// Shared types and module interfaces. Types only: no runtime cost.

export type Scalar = boolean | number | string | null;
export type Features = Record<string, Scalar>;

export type FrictionState = "delivery_uncertainty" | "returns_uncertainty" | "sizing_uncertainty";
export type PageType = "product" | "cart" | "shipping_policy" | "returns_policy" | "other";
export type Device = "mobile" | "tablet" | "desktop";
export type Op = "eq" | "gte" | "lte" | "gt" | "lt";

export type Condition =
  | { f: string; op: Op; v: boolean | number | string }
  | { all: Condition[] }
  | { any: Condition[] };

export interface Rule {
  id: string;
  version: string;
  priority: number;
  friction_state: FrictionState;
  pages: Array<"product" | "cart">;
  when: Condition;
}

export interface ShopConfig {
  schema_version: "1.0";
  shop_id: string;
  mode: "shadow" | "live";
  kill_switch: boolean;
  holdout_bps: number;
  holdout_salt: string;
  log_endpoint: string;
  required_consent: string[];
  consent_ping: boolean;
  selectors: {
    shipping_block: string;
    returns_block: string;
    size_block: string;
    size_chart_trigger: string;
    variant_selector: string;
    add_to_cart_form: string;
  };
  url_patterns: { product: string; cart: string; shipping_policy: string; returns_policy: string };
  rules: Rule[];
  plays: Partial<Record<FrictionState, string[]>>;
  content: {
    delivery_uncertainty?: { by_country?: Record<string, string> };
    returns_uncertainty?: { shop?: string };
    sizing_uncertainty?: { product_ids?: string[] };
  };
}

export interface PageContext {
  page_type: PageType;
  device: Device;
  product_id: string | null;
  country: string | null;
}

// Events as sent to the API (contracts/event-envelope.schema.json).
export interface BaseEvent {
  event_id: string;
  ts: number;
}
export type SdkEvent =
  | (BaseEvent & { type: "page_view" } & PageContext)
  | (BaseEvent & {
      type: "rule_fired";
      decision_id: string;
      friction_state: FrictionState;
      rule_id: string;
      rule_version: string;
      fire_seq: number;
      arm: "holdout" | "treatment";
      mode: "shadow" | "live";
      play: string | null;
      propensity: number | null;
      content_ref: string | null;
      has_content: boolean;
      features: Features;
    })
  | (BaseEvent & {
      type: "page_summary";
      features: Features;
      eval_count: number;
      eval_p50_us: number;
      eval_max_us: number;
    })
  | (BaseEvent & {
      type: "outcome";
      kind: "add_to_cart" | "checkout_started" | "order_completed";
      value: number | null;
      source: "sdk" | "pixel" | "webhook";
    });

// Distributive Omit so callers can pass an event without the ids the transport adds.
export type NewEvent = SdkEvent extends infer E
  ? E extends SdkEvent
    ? Omit<E, "event_id" | "ts">
    : never
  : never;

export interface Envelope {
  schema_version: "1.0";
  shop_id: string;
  visitor_hash?: string;
  session_id: string;
  page_id?: string;
  sent_at: number;
  events: SdkEvent[];
}

// ---- interfaces other modules implement ----

export interface ConsentProvider {
  isGranted(purposes: string[]): boolean;
  onChange(cb: () => void): void;
}

export interface PlatformAdapter {
  getPageContext(): PageContext;
  getCart(): Promise<{ value: number | null }>;
  onAddToCart(cb: () => void): void;
  setCartAttribute(key: string, value: string): void;
}

export interface SessionState {
  sid: string;
  features: Features;
  fired: Partial<Record<FrictionState, true>>;
  fire_seq: number;
}
export interface SessionStore {
  get(): SessionState;
  update(fn: (s: SessionState) => void): void;
}

export interface SignalContext {
  config: ShopConfig;
  page: PageContext;
  /** Called by a collector when its value changed. The feature assembler throttles. */
  changed(): void;
  session: SessionStore;
  /** Subscribe to add-to-cart events from the platform adapter. */
  onAddToCart(cb: () => void): void;
}

export interface SignalCollector {
  id: string;
  start(ctx: SignalContext): void;
  snapshot(): Partial<Features>;
  stop(): void;
}

export interface Transport {
  send(event: NewEvent): void;
  flush(): void;
  stop(): void;
}

export type ConsentOptions =
  | { provider: "shopify" }
  | { provider: "cookie"; name: string; grantedPattern: string }
  | {
      provider: "custom";
      isGranted: (purposes: string[]) => boolean;
      onChange?: (cb: () => void) => void;
    };

export interface InitOptions {
  shopId: string;
  /** Config is fetched from `${configBase}/${shopId}.json`. */
  configBase: string;
  consent: ConsentOptions;
  /** Purposes required before anything happens. The config may add to these. Default ["analytics"]. */
  purposes?: string[];
  platform?: PlatformAdapter;
}
