import type { SignalCollector } from "../types";
import { dwellCollector } from "./dwell";
import { scrollCollector } from "./scroll";
import { sessionCollector } from "./session";
import { tapsCollector } from "./taps";
import { variantsCollector } from "./variants";

/** Adding a signal means adding one file and listing it here. */
export function defaultCollectors(): SignalCollector[] {
  return [dwellCollector(), scrollCollector(), variantsCollector(), tapsCollector(), sessionCollector()];
}
