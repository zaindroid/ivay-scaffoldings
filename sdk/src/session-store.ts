import type { SessionState, SessionStore } from "./types";

// Session-scoped state in sessionStorage under one key. A different session id resets it.
const KEY = "ivay_s";

const fresh = (sid: string): SessionState => ({ sid, features: {}, fired: {}, fire_seq: 0 });

export function createSessionStore(sid: string, storage?: Storage): SessionStore {
  let mem = fresh(sid);
  let st: Storage | null = null;
  try {
    st = storage ?? window.sessionStorage;
    const raw = st.getItem(KEY);
    if (raw) {
      const p = JSON.parse(raw) as SessionState;
      if (p && p.sid === sid && p.features && p.fired) mem = p;
    }
  } catch {
    st = null; // storage blocked: keep state in memory for this page only
  }
  const save = () => {
    try {
      st?.setItem(KEY, JSON.stringify(mem));
    } catch {
      /* quota or blocked */
    }
  };
  save();
  return {
    get: () => mem,
    update(fn) {
      fn(mem);
      save();
    },
  };
}
