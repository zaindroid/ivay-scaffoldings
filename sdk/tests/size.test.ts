import { spawnSync } from "node:child_process";
import { mkdtempSync, writeFileSync } from "node:fs";
import { randomBytes } from "node:crypto";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { describe, expect, it } from "vitest";

// `make size` must fail the build above 10,240 bytes gzipped (spec M8 "done when").
const script = join(__dirname, "..", "scripts", "size.mjs");
const dir = mkdtempSync(join(tmpdir(), "ivay-size-"));

function check(content: Buffer) {
  const file = join(dir, `bundle-${content.length}.js`);
  writeFileSync(file, content);
  const r = spawnSync(process.execPath, [script, file], { encoding: "utf8" });
  return { code: r.status, out: r.stdout, err: r.stderr, gz: gzipSync(content, { level: 9 }).length };
}

describe("size gate", () => {
  it("fails when the gzipped bundle is over 10,240 bytes", () => {
    const r = check(randomBytes(10600)); // random bytes do not compress
    expect(r.gz).toBeGreaterThan(10240);
    expect(r.code).toBe(1);
    expect(r.err).toContain("over the size limit");
  });

  it("passes when the gzipped bundle is under the limit, and reports the size", () => {
    const r = check(randomBytes(9000));
    expect(r.gz).toBeLessThan(10240);
    expect(r.code).toBe(0);
    expect(r.out).toContain(`${r.gz} bytes`);
  });

  it("counts gzipped bytes, not source bytes: a large compressible file passes", () => {
    const r = check(Buffer.from("function f(){return 1}\n".repeat(5000)));
    expect(r.gz).toBeLessThan(2000);
    expect(r.code).toBe(0);
  });
});
