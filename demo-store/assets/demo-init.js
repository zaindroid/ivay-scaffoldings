// Starts the SDK the way a merchant's theme snippet would. The API base defaults to the
// local stack; the E2E tests set window.__IVAY_DEMO_API__ before the page loads.
(function () {
  var api = window.__IVAY_DEMO_API__ || "http://localhost:8000";
  window.Ivay.initIvay({
    shopId: "shop_dev",
    configBase: api + "/v1/config",
    consent: { provider: "shopify" },
    platform: "shopify",
  });
})();
