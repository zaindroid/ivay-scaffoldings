import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";
import { vi } from "vitest";
import type { ShopConfig } from "../src/types";

export const CONTRACTS = join(__dirname, "..", "..", "contracts");

export function fixture<T = unknown>(kind: "valid" | "invalid", name: string): T {
  return JSON.parse(readFileSync(join(CONTRACTS, "fixtures", kind, name), "utf8")) as T;
}
export const fixtureNames = (kind: "valid" | "invalid"): string[] =>
  readdirSync(join(CONTRACTS, "fixtures", kind)).filter((f) => f.endsWith(".json"));

export const fullConfig = (): ShopConfig => fixture<ShopConfig>("valid", "shop-config.full.json");

/** Clear everything the SDK could have written. */
export function resetBrowserState(): void {
  for (const c of document.cookie.split("; ")) {
    const name = c.split("=")[0];
    if (name) document.cookie = `${name}=; Max-Age=0; Path=/`;
  }
  sessionStorage.clear();
  localStorage.clear();
}

export function mockFetchJson(body: unknown, ok = true) {
  const f = vi.fn(async () => ({ ok, json: async () => body }) as unknown as Response);
  vi.stubGlobal("fetch", f);
  return f;
}

export const flush = async (n = 10) => {
  for (let i = 0; i < n; i++) await Promise.resolve();
};
