// Starts the SDK the way a merchant's theme snippet would. The API base defaults to the
// local stack; the E2E tests set window.__IVAY_DEMO_API__ before the page loads. For a manual
// run on another port, open any demo page once with ?api=http://localhost:8001 (remembered).
(function () {
  var api = window.__IVAY_DEMO_API__;
  try {
    var q = new URLSearchParams(window.location.search).get("api");
    if (q) window.localStorage.setItem("demo_api", q);
    if (!api) api = window.localStorage.getItem("demo_api");
  } catch (e) {}
  // Hosted, the API shares the page's origin; on localhost it is the local stack.
  var local = /^(localhost|127\.0\.0\.1)$/.test(window.location.hostname);
  api = api || (local ? "http://localhost:8000" : window.location.origin);
  window.Ivay.initIvay({
    shopId: "shop_dev",
    configBase: api + "/v1/config",
    consent: { provider: "shopify" },
    platform: "shopify",
  });
})();
