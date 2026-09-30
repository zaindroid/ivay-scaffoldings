import { randomId } from "./identity";
import type { Envelope, NewEvent, SdkEvent, Transport } from "./types";

const FLUSH_MS = 5000;
const FLUSH_AT = 20;
const MAX_BYTES = 60000; // per batch (spec 8.8)
const MAX_EVENTS = 100; // envelope schema maxItems

export interface TransportOptions {
  url: string;
  shopId: string;
  /** Identity fields for the envelope, read at flush time. */
  identity(): { visitor_hash?: string; session_id: string; page_id?: string };
}

function post(url: string, body: string): void {
  try {
    if (typeof navigator.sendBeacon === "function" && navigator.sendBeacon(url, body)) return;
  } catch {
    /* fall through to fetch */
  }
  try {
    // No headers: stays a CORS-simple text/plain request, like sendBeacon.
    void fetch(url, { method: "POST", body, keepalive: true, credentials: "omit" }).catch(() => {});
  } catch {
    /* nothing more to do */
  }
}

export function createTransport(o: TransportOptions): Transport {
  let buf: SdkEvent[] = [];
  let timer: ReturnType<typeof setTimeout> | undefined;

  const envelope = (events: SdkEvent[]): string =>
    JSON.stringify({
      schema_version: "1.0",
      shop_id: o.shopId,
      ...o.identity(),
      sent_at: Date.now(),
      events,
    } satisfies Envelope);

  function flush(): void {
    clearTimeout(timer);
    timer = undefined;
    while (buf.length) {
      let n = Math.min(buf.length, MAX_EVENTS);
      let body = envelope(buf.slice(0, n));
      while (body.length > MAX_BYTES && n > 1) {
        n = Math.ceil(n / 2);
        body = envelope(buf.slice(0, n));
      }
      buf = buf.slice(n);
      post(o.url, body);
    }
  }

  const onHide = () => flush();
  const onVis = () => {
    if (document.visibilityState === "hidden") flush();
  };
  window.addEventListener("pagehide", onHide);
  document.addEventListener("visibilitychange", onVis);

  return {
    send(e: NewEvent) {
      buf.push({ ...e, event_id: randomId(12), ts: Date.now() } as SdkEvent);
      if (buf.length >= FLUSH_AT) flush();
      else if (timer === undefined) timer = setTimeout(flush, FLUSH_MS);
    },
    flush,
    stop() {
      clearTimeout(timer);
      buf = [];
      window.removeEventListener("pagehide", onHide);
      document.removeEventListener("visibilitychange", onVis);
    },
  };
}
