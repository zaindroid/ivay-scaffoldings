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
    div.innerHTML =
      '<span>This demo store uses analytics cookies to test Ivay. Allow analytics?</span> ' +
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

  // Cart state lives in the demo's own storage, like a theme's cart drawer would.
  var CART = "demo_cart";
  var SIZES = ["S", "M", "L", "XL"];
  function readCart() {
    try {
      var c = JSON.parse(window.localStorage.getItem(CART));
      if (c && SIZES.indexOf(c.size) >= 0 && c.qty > 0) return { size: c.size, qty: Math.min(c.qty, 9) };
    } catch (e) {}
    return null;
  }
  function writeCart(c) {
    try {
      if (c) window.localStorage.setItem(CART, JSON.stringify(c));
      else window.localStorage.removeItem(CART);
    } catch (e) {}
  }
  function paintBadge() {
    var badge = document.getElementById("cart-count");
    if (!badge) return;
    var c = readCart();
    badge.textContent = c ? String(c.qty) : "0";
    badge.setAttribute("data-empty", c ? "false" : "true");
  }
  function eur(n) {
    return "€" + n.toFixed(2);
  }
  function make(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined) e.textContent = text;
    return e;
  }
  function paintCart() {
    var root = document.getElementById("cart-root");
    if (!root) return;
    root.textContent = "";
    var c = readCart();
    if (!c) {
      var empty = make("div", "empty");
      empty.appendChild(make("h2", null, "Your cart is empty"));
      empty.appendChild(make("p", null, "Add the Everyday Tee to see it here."));
      var go = make("a", "btn", "Shop the Everyday Tee");
      go.href = "/products/tee.html";
      empty.appendChild(go);
      root.appendChild(empty);
      return;
    }
    var lines = make("div", "lines");
    var line = make("div", "line");
    var panel = make("div", "panel");
    var img = make("img");
    img.src = "/assets/tee.svg";
    img.alt = "";
    panel.appendChild(img);
    var info = make("div");
    info.appendChild(make("strong", null, "Everyday Tee"));
    info.appendChild(make("small", null, "Size " + c.size + ", quantity " + c.qty));
    var rm = make("button", "btn btn-quiet", "Remove");
    rm.type = "button";
    rm.addEventListener("click", function () {
      writeCart(null);
      paintBadge();
      paintCart();
    });
    info.appendChild(rm);
    line.appendChild(panel);
    line.appendChild(info);
    line.appendChild(make("strong", null, eur(29 * c.qty)));
    lines.appendChild(line);

    var sum = make("form", "summary");
    sum.method = "post";
    sum.action = "/cart";
    var dl = make("dl");
    [["Subtotal", eur(29 * c.qty)], ["Delivery", "Free"]].forEach(function (r) {
      var d = make("div");
      d.appendChild(make("dt", null, r[0]));
      d.appendChild(make("dd", null, r[1]));
      dl.appendChild(d);
    });
    var total = make("div", "total");
    total.appendChild(make("dt", null, "Total"));
    total.appendChild(make("dd", null, eur(29 * c.qty)));
    dl.appendChild(total);
    sum.appendChild(dl);
    var btn = make("button", "btn btn-block", "Check out");
    btn.type = "submit";
    btn.name = "checkout";
    sum.appendChild(btn);
    var note = make("p", null, "");
    note.id = "demo-checkout-note";
    note.setAttribute("role", "status");
    sum.appendChild(note);
    sum.addEventListener("submit", function (e) {
      e.preventDefault();
      note.textContent = "This is a demo store, so checkout is turned off. Nothing was ordered.";
    });
    root.appendChild(lines);
    root.appendChild(sum);
  }

  // A theme that adds to cart with fetch and keeps the page in place.
  document.addEventListener("submit", function (e) {
    var form = e.target;
    if (form && form.matches && form.matches("form[action*='/cart/add']")) {
      e.preventDefault();
      var picked = form.querySelector("[name='id']:checked");
      var size = picked && picked.getAttribute("data-label");
      var cur = readCart();
      writeCart({ size: SIZES.indexOf(size) >= 0 ? size : "M", qty: cur && cur.size === size ? cur.qty + 1 : 1 });
      paintBadge();
      // The status text is the only thing in <main> the demo changes (the SDK must change nothing).
      var status = document.getElementById("demo-atc-status");
      if (status) status.textContent = "Added to cart";
    }
  });

  function ready() {
    showBanner();
    paintBadge();
    paintCart();
  }

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", ready);
  else ready();
})();
