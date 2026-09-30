import { randomId, sha256Hex } from "./identity";
import type { Features, FrictionState, PageContext, Rule, SdkEvent, ShopConfig } from "./types";

export type Arm = "holdout" | "treatment";

/**
 * Arm = first 8 hex chars of SHA-256(visitor_hash + holdout_salt) as an integer, modulo 10000.
 * Below holdout_bps is "holdout". Stable per visitor and independent of the session.
 */
export async function assignArm(visitorHash: string, salt: string, holdoutBps: number): Promise<Arm> {
  const h = await sha256Hex(visitorHash + salt);
  return parseInt(h.slice(0, 8), 16) % 10000 < holdoutBps ? "holdout" : "treatment";
}

/**
 * Coverage lookup. The config's `content` block is an index of what the merchant data can
 * answer, not the answers. No coverage gives `{ content_ref: null, has_content: false }`.
 */
export function lookupContent(
  config: ShopConfig,
  state: FrictionState,
  page: Pick<PageContext, "product_id" | "country">,
): { content_ref: string | null; has_content: boolean } {
  const none = { content_ref: null, has_content: false };
  const c = config.content;
  if (state === "delivery_uncertainty") {
    const ref = page.country ? c.delivery_uncertainty?.by_country?.[page.country] : undefined;
    return ref ? { content_ref: ref, has_content: true } : none;
  }
  if (state === "returns_uncertainty") {
    const ref = c.returns_uncertainty?.shop;
    return ref ? { content_ref: ref, has_content: true } : none;
  }
  const covered = !!page.product_id && !!c.sizing_uncertainty?.product_ids?.includes(page.product_id);
  return covered ? { content_ref: `size_chart:${page.product_id}`, has_content: true } : none;
}

/**
 * Shadow mode never picks a play, so play and propensity are null. (Live mode, not built in
 * Phase 0, would pick uniformly and log propensity = 1 / number of plays; never a constant.)
 */
export function buildDecision(
  config: ShopConfig,
  rule: Rule,
  fireSeq: number,
  arm: Arm,
  page: PageContext,
  features: Features,
): Omit<Extract<SdkEvent, { type: "rule_fired" }>, "event_id" | "ts"> {
  return {
    type: "rule_fired",
    decision_id: randomId(12),
    friction_state: rule.friction_state,
    rule_id: rule.id,
    rule_version: rule.version,
    fire_seq: fireSeq,
    arm,
    mode: config.mode,
    play: null,
    propensity: null,
    ...lookupContent(config, rule.friction_state, page),
    features,
  };
}
