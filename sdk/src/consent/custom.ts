import type { ConsentProvider } from "../types";

export function customConsent(
  isGranted: (purposes: string[]) => boolean,
  onChange?: (cb: () => void) => void,
): ConsentProvider {
  return {
    isGranted: (p) => isGranted(p) === true,
    onChange: (cb) => onChange?.(cb),
  };
}
