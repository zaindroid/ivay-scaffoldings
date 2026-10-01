// Stands in for what a Shopify theme provides: the storefront globals the SDK reads, a
// consent banner that drives the Customer Privacy API surface, and a theme-style add-to-cart
// that intercepts the form submit. Demo only: nothing here is part of the SDK.
(function () {
  var KEY = "demo_consent"; // the demo banner's own storage, not the SDK's

  function choice() {
    try {
      return window.localStorage.getItem(KEY);
    } catch (e) {
      return null;
    }
  }

  window.Shopify = window.Shopify || {};
  window.Shopify.country = "DE";
  window.Shopify.routes = { root: "/" };
  window.Shopify.customerPrivacy = {
    analyticsProcessingAllowed: function () {
      return choice() === "yes";
    },
    marketingAllowed: function () {
      return false;
    },
    preferencesProcessingAllowed: function () {
      return false;
    },
    saleOfDataAllowed: function () {
      return false;
    },
  };

  function decide(value) {
    try {
      window.localStorage.setItem(KEY, value);
    } catch (e) {}
    var banner = document.getElementById("demo-consent");
    if (banner) banner.remove();
    document.dispatchEvent(
      new CustomEvent("visitorConsentCollected", { detail: { analyticsAllowed: value === "yes" } }),
    );
  }

  function showBanner() {
    if (choice() !== null) return;
    var div = document.createElement("div");
    div.id = "demo-consent";
    div.setAttribute("style", "position:fixed;bottom:0;left:0;right:0;background:#eee;padding:8px;z-index:9");
    div.innerHTML =
      '<span>Demo cookie banner: allow analytics?</span> ' +
      '<button id="demo-consent-accept" type="button">Accept</button> ' +
      '<button id="demo-consent-decline" type="button">Decline</button>';
    document.body.appendChild(div);
    document.getElementById("demo-consent-accept").addEventListener("click", function () {
      decide("yes");
    });
    document.getElementById("demo-consent-decline").addEventListener("click", function () {
      decide("no");
    });
  }

  // A theme that adds to cart with fetch and keeps the page in place.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form && form.matches && form.matches("form[action*='/cart/add']")) {
      e.preventDefault();
      var status = document.getElementById("demo-atc-status");
      if (status) status.textContent = "Added to cart";
    }
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", showBanner);
  else showBanner();
})();
