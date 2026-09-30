import { cookieConsent } from "./consent/cookie";
import { customConsent } from "./consent/custom";
import { shopifyConsent } from "./consent/shopify";
import { fetchConfig } from "./config";
import { createGuard } from "./guard";
import { getVisitorId, randomId, touchSession, visitorHash } from "./identity";
import { createSessionStore } from "./session-store";
import { createTransport } from "./transport";
import type { ConsentProvider, InitOptions } from "./types";

function resolveConsent(o: InitOptions["consent"]): ConsentProvider {
  if (o.provider === "shopify") return shopifyConsent();
  if (o.provider === "cookie") return cookieConsent(o.name, o.grantedPattern);
  return customConsent(o.isGranted, o.onChange);
}

/**
 * Start-up sequence (spec 8.1). Nothing is created, stored or sent until consent is granted.
 * Later milestones extend `boot` (signals, rules, decisions); this file is wiring only.
 */
export function initIvay(opts: InitOptions): { stop(): void } {
  const stops: Array<() => void> = [];
  let stopped = false;
  const stop = () => {
    stopped = true;
    for (const s of stops.splice(0)) {
      try {
        s();
      } catch {
        /* ignore */
      }
    }
  };
  const guard = createGuard(stop);
  const purposes = opts.purposes ?? ["analytics"];
  let running = false;

  async function boot(consent: ConsentProvider): Promise<void> {
    // 3. Config. The fetch carries no identifier and nothing is stored yet.
    const config = await fetchConfig(`${opts.configBase}/${opts.shopId}.json`);
    if (!config || config.kill_switch || stopped) return;
    // The config may require more than the init purposes. Not granted: stay inert, and a
    // later consent change tries again.
    if (!consent.isGranted(config.required_consent)) {
      running = false;
      return;
    }
    // 4. Identity and session.
    const vid = getVisitorId();
    const sid = touchSession();
    const hash = await visitorHash(vid, config.holdout_salt);
    const store = createSessionStore(sid);
    const pageId = randomId(12);
    const transport = createTransport({
      url: config.log_endpoint,
      shopId: config.shop_id,
      identity: () => ({ visitor_hash: hash, session_id: touchSession(), page_id: pageId }),
    });
    stops.push(transport.stop);
    void store;
    // 5. page_view, collectors and rules arrive in M2 to M4.
    if (opts.platform) transport.send({ type: "page_view", ...opts.platform.getPageContext() });
  }

  // 1. Consent provider comes from the init options, not the remote config.
  const consent = resolveConsent(opts.consent);
  const tryStart = guard.wrap(async () => {
    if (running || stopped || !consent.isGranted(purposes)) return;
    running = true;
    await boot(consent);
  });
  tryStart();
  // 2. Consent arriving later starts the SDK.
  guard.wrap(() => consent.onChange(tryStart))();
  return { stop };
}
