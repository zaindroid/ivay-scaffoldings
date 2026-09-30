import type { ConsentProvider } from "../types";

// Shopify Customer Privacy API: window.Shopify.customerPrivacy.*Allowed() and the
// `visitorConsentCollected` document event. Verified against shopify.dev, see NOTES.md (S1).
interface Privacy {
  analyticsProcessingAllowed(): boolean;
  marketingAllowed(): boolean;
  preferencesProcessingAllowed(): boolean;
  saleOfDataAllowed(): boolean;
}

const check: Record<string, keyof Privacy> = {
  analytics: "analyticsProcessingAllowed",
  marketing: "marketingAllowed",
  preferences: "preferencesProcessingAllowed",
  sale_of_data: "saleOfDataAllowed",
};

export function shopifyConsent(): ConsentProvider {
  return {
    isGranted(purposes) {
      const p = (window as unknown as { Shopify?: { customerPrivacy?: Privacy } }).Shopify
        ?.customerPrivacy;
      // API missing or unknown purpose: not granted.
      return !!p && purposes.every((x) => check[x] !== undefined && p[check[x]]() === true);
    },
    onChange(cb) {
      document.addEventListener("visitorConsentCollected", () => cb());
    },
  };
}
