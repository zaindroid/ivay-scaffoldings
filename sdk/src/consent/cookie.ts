import type { ConsentProvider } from "../types";

export function readCookie(name: string): string | null {
  for (const part of document.cookie.split("; ")) {
    const i = part.indexOf("=");
    if (i > 0 && part.slice(0, i) === name) return part.slice(i + 1);
  }
  return null;
}

// For shops whose consent tool writes a cookie. `grantedPattern` is a regex source tested
// against the cookie value. Cookie changes have no event, so it is polled until granted.
export function cookieConsent(name: string, grantedPattern: string): ConsentProvider {
  let re: RegExp | null = null;
  try {
    re = new RegExp(grantedPattern);
  } catch {
    /* bad pattern: never granted */
  }
  const granted = () => {
    const v = readCookie(name);
    return !!re && v !== null && re.test(decodeURIComponent(v));
  };
  return {
    isGranted: granted,
    onChange(cb) {
      const t = setInterval(() => {
        if (granted()) {
          clearInterval(t);
          cb();
        }
      }, 1000);
    },
  };
}
