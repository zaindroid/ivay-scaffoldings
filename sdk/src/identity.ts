import { readCookie } from "./consent/cookie";

// Nothing in this file may run before consent (see index.ts).

const VID = "ivay_vid";
const SID = "ivay_sid";
const YEAR = 31536000;
// 30 min of inactivity ends the session: the cookie expiry is pushed out on every touch.
const SESSION_TTL = 1800;

export function randomId(bytes = 16): string {
  const a = new Uint8Array(bytes);
  crypto.getRandomValues(a);
  let s = "";
  for (let i = 0; i < a.length; i++) s += (a[i] < 16 ? "0" : "") + a[i].toString(16);
  return s;
}

export async function sha256Hex(text: string): Promise<string> {
  const d = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(d), (b) => (b < 16 ? "0" : "") + b.toString(16)).join("");
}

function setCookie(name: string, value: string, maxAge: number): void {
  const secure = location.protocol === "https:" ? "; Secure" : "";
  document.cookie = `${name}=${value}; Max-Age=${maxAge}; Path=/; SameSite=Lax${secure}`;
}

/** Raw visitor id. It stays in the cookie and is only ever sent hashed. */
export function getVisitorId(): string {
  let v = readCookie(VID);
  if (!v || !/^[0-9a-f]{32}$/.test(v)) v = randomId(16);
  setCookie(VID, v, YEAR);
  return v;
}

export const visitorHash = (vid: string, salt: string): Promise<string> => sha256Hex(vid + salt);

/** Current session id, creating one if the cookie expired. Each call extends the session. */
export function touchSession(): string {
  let s = readCookie(SID);
  if (!s || !/^[0-9a-f]{24}$/.test(s)) s = randomId(12);
  setCookie(SID, s, SESSION_TTL);
  return s;
}
