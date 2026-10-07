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
  api = api || "http://localhost:8000";
  window.Ivay.initIvay({
    shopId: "shop_dev",
    configBase: api + "/v1/config",
    consent: { provider: "shopify" },
    platform: "shopify",
  });
})();
