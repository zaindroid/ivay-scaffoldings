import { buildDecision, type Arm } from "./decision";
import type { Condition, Features, NewEvent, PageContext, SessionStore, ShopConfig } from "./types";

/** Interprets a rule condition. A missing or null feature makes its leaf false (A7 in NOTES.md). */
export function evalCondition(c: Condition, f: Features): boolean {
  if ("all" in c) return c.all.every((x) => evalCondition(x, f));
  if ("any" in c) return c.any.some((x) => evalCondition(x, f));
  const x = f[c.f];
  if (x === undefined || x === null) return false;
  if (c.op === "eq") return x === c.v;
  if (typeof x !== "number" || typeof c.v !== "number") return false;
  if (c.op === "gte") return x >= c.v;
  if (c.op === "lte") return x <= c.v;
  if (c.op === "gt") return x > c.v;
  return x < c.v;
}

export interface EvalStats {
  eval_count: number;
  eval_p50_us: number;
  eval_max_us: number;
}

export interface RuleEngine {
  /** Evaluate every eligible rule against the features; send a rule_fired event per new firing. */
  evaluate(features: Features): void;
  stats(): EvalStats;
}

const MAX_SAMPLES = 2000;

export function createRuleEngine(o: {
  config: ShopConfig;
  page: PageContext;
  session: SessionStore;
  arm: Arm;
  send(e: NewEvent): void;
}): RuleEngine {
  // Priority order decides the sequence when several rules fire in the same tick; ties by id.
  const rules = o.config.rules
    .filter((r) => r.pages.includes(o.page.page_type as "product" | "cart"))
    .sort((a, b) => a.priority - b.priority || (a.id < b.id ? -1 : 1));
  const samples: number[] = [];
  let count = 0;
  let max = 0;

  return {
    evaluate(features) {
      const t0 = performance.now();
      for (const r of rules) {
        // At most one firing per friction state per session; the store remembers across pages.
        if (o.session.get().fired[r.friction_state]) continue;
        if (!evalCondition(r.when, features)) continue;
        let seq = 0;
        o.session.update((s) => {
          s.fired[r.friction_state] = true;
          seq = ++s.fire_seq;
        });
        o.send(buildDecision(o.config, r, seq, o.arm, o.page, features));
      }
      const us = (performance.now() - t0) * 1000;
      count++;
      if (us > max) max = us;
      if (samples.length < MAX_SAMPLES) samples.push(us);
      else samples[count % MAX_SAMPLES] = us;
    },
    stats() {
      const s = [...samples].sort((a, b) => a - b);
      return {
        eval_count: count,
        eval_p50_us: s.length ? Math.round(s[Math.floor((s.length - 1) / 2)] * 10) / 10 : 0,
        eval_max_us: Math.round(max * 10) / 10,
      };
    },
  };
}
