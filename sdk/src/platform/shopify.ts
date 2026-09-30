import type { Device, PageContext, PageType, PlatformAdapter, ShopConfig } from "../types";

// Shopify storefront adapter. Every global and endpoint used here is listed in NOTES.md
// (S4 to S9) with whether it was verified against shopify.dev or must be checked on a real shop.
interface Globals {
  Shopify?: { country?: string; routes?: { root?: string } };
  ShopifyAnalytics?: { meta?: { product?: { id?: number | string } } };
}
interface CartJson {
  total_price?: number;
  attributes?: Record<string, unknown>;
}

const g = (): Globals => window as unknown as Globals;

/** Locale-aware storefront root, e.g. "/" or "/de/". Shopify.routes.root (Ajax API docs). */
function root(): string {
  const r = g().Shopify?.routes?.root;
  return typeof r === "string" && r.startsWith("/") && r.endsWith("/") ? r : "/";
}

function matcher(src: string): RegExp | null {
  try {
    return new RegExp(src);
  } catch {
    return null;
  }
}

export function shopifyPlatform(config: ShopConfig): PlatformAdapter {
  const patterns: Array<[PageType, RegExp | null]> = [
    ["product", matcher(config.url_patterns.product)],
    ["cart", matcher(config.url_patterns.cart)],
    ["shipping_policy", matcher(config.url_patterns.shipping_policy)],
    ["returns_policy", matcher(config.url_patterns.returns_policy)],
  ];
  let cart: Promise<CartJson | null> | undefined;

  // One same-origin request to /cart.js per page load, shared by getCart and setCartAttribute.
  const cartJson = (): Promise<CartJson | null> =>
    (cart ??= (async () => {
      try {
        const res = await fetch(`${root()}cart.js`, { credentials: "same-origin" });
        return res.ok ? ((await res.json()) as CartJson) : null;
      } catch {
        return null;
      }
    })());

  function pageType(): PageType {
    const r = root();
    const p = location.pathname;
    const path = r !== "/" && p.startsWith(r) ? "/" + p.slice(r.length) : p; // drop the /de/ prefix
    for (const [type, re] of patterns) if (re && re.test(path)) return type;
    return "other";
  }

  function device(): Device {
    const coarse = typeof matchMedia === "function" && matchMedia("(pointer: coarse)").matches;
    if (window.innerWidth < 768) return "mobile";
    return coarse ? "tablet" : "desktop";
  }

  return {
    getPageContext(): PageContext {
      const type = pageType();
      const id = g().ShopifyAnalytics?.meta?.product?.id;
      const country = String(g().Shopify?.country ?? "").toUpperCase();
      return {
        page_type: type,
        device: device(),
        product_id: type === "product" && id !== undefined && id !== null ? String(id) : null,
        country: /^[A-Z]{2}$/.test(country) ? country : null,
      };
    },
    async getCart() {
      const c = await cartJson();
      // total_price is in the smallest currency unit (cents) in the presentment currency.
      return { value: c && typeof c.total_price === "number" ? c.total_price / 100 : null };
    },
    onAddToCart(cb) {
      // Submit on the add-to-cart form. No fetch or XHR patching. A submit is an attempt: the
      // theme may still reject it (sold out).
      document.addEventListener(
        "submit",
        (e) => {
          try {
            if ((e.target as Element).matches(config.selectors.add_to_cart_form)) cb();
          } catch {
            /* invalid selector or non-element target */
          }
        },
        { capture: true, passive: true },
      );
    },
    async setCartAttribute(key, value) {
      const c = await cartJson();
      // Only write when the cart is known and the attribute is missing or different.
      if (!c || c.attributes?.[key] === value) return;
      try {
        await fetch(`${root()}cart/update.js`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ attributes: { [key]: value } }),
          credentials: "same-origin",
        });
      } catch {
        /* the order join then falls back to the pixel outcome */
      }
    },
  };
}
