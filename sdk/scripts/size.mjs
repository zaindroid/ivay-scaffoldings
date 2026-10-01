// Fails the build when the production bundle exceeds 10,240 bytes gzipped (spec 3, 8).
// Usage: node scripts/size.mjs [bundle]   (default: dist/ivay.js)
import { readFileSync } from "node:fs";
import { gzipSync } from "node:zlib";

const LIMIT = 10240;
const file = process.argv[2] ?? new URL("../dist/ivay.js", import.meta.url);
const bytes = gzipSync(readFileSync(file), { level: 9 }).length;
console.log(`ivay.js gzipped: ${bytes} bytes (limit ${LIMIT})`);
if (bytes > LIMIT) {
  console.error("SDK bundle is over the size limit");
  process.exit(1);
}
