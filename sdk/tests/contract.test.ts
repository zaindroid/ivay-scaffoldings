import { readFileSync } from "node:fs";
import { join } from "node:path";
import Ajv2020 from "ajv/dist/2020";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { validateConfig } from "../src/config";
import { createTransport } from "../src/transport";
import { CONTRACTS, fixture, fixtureNames } from "./helpers";

// Same shared fixtures and manifest as api/tests/test_contracts.py.
const manifest = JSON.parse(
  readFileSync(join(CONTRACTS, "fixtures", "manifest.json"), "utf8"),
).invalid as Record<string, string>;

describe("shop config: SDK validator vs shared fixtures", () => {
  for (const name of fixtureNames("valid").filter((n) => n.startsWith("shop-config"))) {
    it(`accepts valid/${name}`, () => expect(validateConfig(fixture("valid", name))).toBe(true));
  }
  for (const name of fixtureNames("invalid").filter((n) => n.startsWith("shop-config"))) {
    it(`rejects invalid/${name}`, () => expect(validateConfig(fixture("invalid", name))).toBe(false));
  }
  it("rejects non-objects", () => {
    for (const x of [null, 1, "x", [], undefined]) expect(validateConfig(x)).toBe(false);
  });
  it("manifest and directory agree", () => {
    expect(new Set(Object.keys(manifest))).toEqual(new Set(fixtureNames("invalid")));
  });
});

describe("events the SDK sends validate against the envelope schema", () => {
  const ajv = new Ajv2020({ allErrors: true, strict: false });
  const validate = ajv.compile(
    JSON.parse(readFileSync(join(CONTRACTS, "event-envelope.schema.json"), "utf8")),
  );
  let sent: string[];
  beforeEach(() => {
    sent = [];
    Object.defineProperty(navigator, "sendBeacon", {
      configurable: true,
      value: (_u: string, b: string) => (sent.push(b), true),
    });
  });
  afterEach(() => vi.restoreAllMocks());

  it("a batch with every event type is valid", () => {
    const t = createTransport({
      url: "http://x/v1/events",
      shopId: "shop_dev",
      identity: () => ({ visitor_hash: "a".repeat(64), session_id: "s".repeat(24), page_id: "p".repeat(24) }),
    });
    t.send({ type: "page_view", page_type: "product", device: "desktop", product_id: "4821", country: "DE" });
    t.send({
      type: "rule_fired", decision_id: "d".repeat(24), friction_state: "delivery_uncertainty",
      rule_id: "delivery_v1", rule_version: "r1", fire_seq: 1, arm: "holdout", mode: "shadow",
      play: null, propensity: null, content_ref: null, has_content: false, features: { a: 1, b: null },
    });
    t.send({ type: "page_summary", features: { a: true }, eval_count: 3, eval_p50_us: 10, eval_max_us: 20 });
    t.send({ type: "outcome", kind: "add_to_cart", value: null, source: "sdk" });
    t.flush();
    t.stop();
    expect(sent).toHaveLength(1);
    const body = JSON.parse(sent[0]);
    expect(validate(body), JSON.stringify(validate.errors)).toBe(true);
  });
});
