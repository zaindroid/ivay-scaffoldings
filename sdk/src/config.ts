import type { ShopConfig } from "./types";

// Hand-written validator for contracts/shop-config.schema.json (a JSON Schema library would
// blow the size budget). tests/contract.test.ts runs every shared fixture through it.

type Rec = Record<string, unknown>;
const isObj = (x: unknown): x is Rec => typeof x === "object" && x !== null && !Array.isArray(x);
const str = (x: unknown, max = 1e6): x is string =>
  typeof x === "string" && x.length > 0 && x.length <= max;
const exact = (o: Rec, req: string[], opt: string[] = []) =>
  req.every((k) => k in o) && Object.keys(o).every((k) => req.includes(k) || opt.includes(k));
const strList = (x: unknown, min: number): boolean =>
  Array.isArray(x) &&
  x.length >= min &&
  x.every((s) => str(s)) &&
  new Set(x as string[]).size === x.length;

const FRICTION = ["delivery_uncertainty", "returns_uncertainty", "sizing_uncertainty"];
const OPS = ["eq", "gte", "lte", "gt", "lt"];

function cond(c: unknown, depth: number): boolean {
  if (!isObj(c) || depth > 8) return false;
  if ("f" in c) {
    return (
      exact(c, ["f", "op", "v"]) &&
      typeof c.f === "string" &&
      /^[a-z][a-z0-9_]*$/.test(c.f) &&
      OPS.includes(c.op as string) &&
      ["boolean", "number", "string"].includes(typeof c.v)
    );
  }
  const k = "all" in c ? "all" : "any";
  const list = c[k];
  return (
    exact(c, [k]) && Array.isArray(list) && list.length > 0 && list.every((x) => cond(x, depth + 1))
  );
}

function rule(r: unknown): boolean {
  return (
    isObj(r) &&
    exact(r, ["id", "version", "priority", "friction_state", "pages", "when"]) &&
    str(r.id) &&
    str(r.version) &&
    Number.isInteger(r.priority) &&
    (r.priority as number) >= 0 &&
    FRICTION.includes(r.friction_state as string) &&
    Array.isArray(r.pages) &&
    r.pages.length > 0 &&
    new Set(r.pages).size === r.pages.length &&
    r.pages.every((p) => p === "product" || p === "cart") &&
    cond(r.when, 0)
  );
}

function regex(x: unknown): boolean {
  if (!str(x)) return false;
  try {
    new RegExp(x);
    return true;
  } catch {
    return false;
  }
}

function content(c: unknown): boolean {
  if (!isObj(c) || !exact(c, [], FRICTION)) return false;
  const d = c.delivery_uncertainty;
  if (d !== undefined) {
    if (!isObj(d) || !exact(d, [], ["by_country"])) return false;
    const bc = d.by_country;
    if (bc !== undefined) {
      if (!isObj(bc)) return false;
      for (const k of Object.keys(bc)) if (!/^[A-Z]{2}$/.test(k) || !str(bc[k])) return false;
    }
  }
  const r = c.returns_uncertainty;
  if (r !== undefined && !(isObj(r) && exact(r, [], ["shop"]) && (r.shop === undefined || str(r.shop))))
    return false;
  const s = c.sizing_uncertainty;
  if (
    s !== undefined &&
    !(isObj(s) && exact(s, [], ["product_ids"]) && (s.product_ids === undefined || strList(s.product_ids, 0)))
  )
    return false;
  return true;
}

export function validateConfig(c: unknown): c is ShopConfig {
  if (
    !isObj(c) ||
    !exact(c, [
      "schema_version", "shop_id", "mode", "kill_switch", "holdout_bps", "holdout_salt",
      "log_endpoint", "required_consent", "consent_ping", "selectors", "url_patterns",
      "rules", "plays", "content",
    ])
  )
    return false;
  const sel = c.selectors;
  const url = c.url_patterns;
  const plays = c.plays;
  return (
    c.schema_version === "1.0" &&
    str(c.shop_id, 64) &&
    (c.mode === "shadow" || c.mode === "live") &&
    typeof c.kill_switch === "boolean" &&
    Number.isInteger(c.holdout_bps) &&
    (c.holdout_bps as number) >= 0 &&
    (c.holdout_bps as number) <= 10000 &&
    str(c.holdout_salt) &&
    str(c.log_endpoint) &&
    /^https?:\/\//.test(c.log_endpoint) &&
    strList(c.required_consent, 1) &&
    typeof c.consent_ping === "boolean" &&
    isObj(sel) &&
    exact(sel, [
      "shipping_block", "returns_block", "size_block", "size_chart_trigger",
      "variant_selector", "add_to_cart_form",
    ]) &&
    Object.values(sel).every((v) => str(v)) &&
    isObj(url) &&
    exact(url, ["product", "cart", "shipping_policy", "returns_policy"]) &&
    Object.values(url).every(regex) &&
    Array.isArray(c.rules) &&
    c.rules.every(rule) &&
    isObj(plays) &&
    Object.keys(plays).every((k) => FRICTION.includes(k) && strList(plays[k], 1)) &&
    content(c.content)
  );
}

/** Fetch and validate. Any failure returns null and the SDK stays inert: there is no default rule set. */
export async function fetchConfig(url: string): Promise<ShopConfig | null> {
  try {
    const res = await fetch(url, { credentials: "omit" });
    if (!res.ok) return null;
    const json: unknown = await res.json();
    return validateConfig(json) ? json : null;
  } catch {
    return null;
  }
}
