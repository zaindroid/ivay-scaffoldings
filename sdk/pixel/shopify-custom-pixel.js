// Ivay checkout outcomes: a Shopify custom pixel.
// Paste into Shopify admin > Settings > Customer events > Add custom pixel. Set its permission
// to "Analytics" so it only runs for shoppers who consented. Edit the two constants below.
//
// It posts one `outcome` event when checkout starts and one when it completes. It sends
// nothing unless the shopper has an Ivay session id, and that id only exists after the SDK
// received consent on the storefront. It sends no name, email, address or order contents:
// only the event kind, the checkout total and the session id.

const IVAY_ENDPOINT = "https://YOUR-IVAY-API/v1/events";
const IVAY_SHOP_ID = "YOUR_SHOP_ID";

const ID_PATTERN = /^[A-Za-z0-9_-]{8,64}$/;

// The SDK writes the session id to the cart as the attribute "ivay_sid", which checkout events
// carry in data.checkout.attributes. The ivay_sid cookie is the fallback.
async function sessionId(event) {
  try {
    const attrs = (event && event.data && event.data.checkout && event.data.checkout.attributes) || [];
    const hit = attrs.find((a) => a && a.key === "ivay_sid");
    if (hit && ID_PATTERN.test(hit.value)) return hit.value;
  } catch (e) {}
  try {
    const c = await browser.cookie.get("ivay_sid");
    if (c && ID_PATTERN.test(c)) return c;
  } catch (e) {}
  return null;
}

async function report(kind, prefix, event) {
  try {
    const sid = await sessionId(event);
    if (!sid) return; // no consented SDK session: send nothing

    const total = event.data && event.data.checkout && event.data.checkout.totalPrice;
    const value = total && typeof total.amount === "number" ? total.amount : null;
    const body = JSON.stringify({
      schema_version: "1.0",
      shop_id: IVAY_SHOP_ID,
      session_id: sid,
      sent_at: Date.now(),
      events: [
        {
          type: "outcome",
          // Stable id per session and kind: a repeated event is deduplicated by the API.
          event_id: prefix + "_" + sid,
          ts: Date.now(),
          kind: kind,
          value: value,
          source: "pixel",
        },
      ],
    });
    // No headers: a CORS-simple text/plain POST, like the SDK's beacon. keepalive lets it
    // outlive the page (Shopify deprecates browser.sendBeacon in favour of this).
    fetch(IVAY_ENDPOINT, { method: "POST", body: body, keepalive: true }).catch(() => {});
  } catch (e) {
    // Never disturb checkout.
  }
}

analytics.subscribe("checkout_started", (event) => report("checkout_started", "pxstart", event));
analytics.subscribe("checkout_completed", (event) => report("order_completed", "pxorder", event));
