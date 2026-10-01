import { expect, type Page, type Request } from "@playwright/test";
import pg from "pg";

export const API = `http://localhost:${process.env.API_PORT ?? "8000"}`;
const DATABASE_URL =
  process.env.E2E_DATABASE_URL ?? "postgresql://ivay:ivay_dev@127.0.0.1:5432/ivay";

export const pool = new pg.Pool({ connectionString: DATABASE_URL, max: 2 });

const EVENT_TABLES = ["page_view", "decision_log", "page_summary", "outcome_event", "consent_ping_daily"];

export async function resetEvents(): Promise<void> {
  await pool.query(`TRUNCATE ${EVENT_TABLES.join(", ")}`);
}

export async function rows<T = Record<string, unknown>>(sql: string, params: unknown[] = []): Promise<T[]> {
  return (await pool.query(sql, params)).rows as T[];
}

export async function totalEventRows(): Promise<number> {
  let n = 0;
  for (const t of EVENT_TABLES) n += Number((await rows(`SELECT count(*) AS n FROM ${t}`))[0].n);
  return n;
}

/** Poll the database until `check` passes. Beacons are asynchronous, so rows arrive a moment later. */
export async function eventually<T>(fn: () => Promise<T>, ok: (v: T) => boolean, what: string): Promise<T> {
  const deadline = Date.now() + 15_000;
  let last: T | undefined;
  while (Date.now() < deadline) {
    last = await fn();
    if (ok(last)) return last;
    await new Promise((r) => setTimeout(r, 200));
  }
  throw new Error(`timed out waiting for ${what}; last value: ${JSON.stringify(last)}`);
}

export interface Recorder {
  apiRequests: string[];
  cartUpdates: Array<Record<string, unknown>>;
  cartReads: number;
}

/** Point the demo pages at this stack's API and stand in for the two Shopify cart endpoints. */
export async function prepare(page: Page): Promise<Recorder> {
  const rec: Recorder = { apiRequests: [], cartUpdates: [], cartReads: 0 };
  await page.addInitScript((api: string) => {
    (window as unknown as { __IVAY_DEMO_API__: string }).__IVAY_DEMO_API__ = api;
  }, API);
  page.on("request", (req: Request) => {
    if (req.url().startsWith(`${API}/v1/`)) rec.apiRequests.push(`${req.method()} ${new URL(req.url()).pathname}`);
  });
  // Like Shopify, the cart remembers attributes that were written to it.
  const attributes: Record<string, unknown> = {};
  await page.route("**/cart.js", async (route) => {
    rec.cartReads++;
    await route.fulfill({ json: { total_price: 2900, currency: "EUR", attributes } });
  });
  await page.route("**/cart/update.js", async (route) => {
    const body = JSON.parse(route.request().postData() ?? "{}") as { attributes?: Record<string, unknown> };
    rec.cartUpdates.push(body);
    Object.assign(attributes, body.attributes ?? {});
    await route.fulfill({ json: { attributes } });
  });
  return rec;
}

export async function ivayStorage(page: Page): Promise<{ cookies: string[]; session: string | null; local: string[] }> {
  return page.evaluate(() => ({
    cookies: document.cookie.split("; ").filter((c) => c.startsWith("ivay_")),
    session: window.sessionStorage.getItem("ivay_s"),
    local: Object.keys(window.localStorage).filter((k) => k.startsWith("ivay")),
  }));
}

export async function cookieValue(page: Page, name: string): Promise<string | undefined> {
  const all = await page.context().cookies();
  return all.find((c) => c.name === name)?.value;
}

export { expect };
