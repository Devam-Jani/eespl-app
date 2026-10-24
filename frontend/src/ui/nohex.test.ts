import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// The token file is the one place colours live: no hex colour in any page, component or stylesheet.
const SRC = resolve(__dirname, "..");
const ALLOWED = new Set(["ui/tokens.ts", "ui/tokens.css"]);
const HEX = /#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b(?![0-9a-zA-Z-])|0x[0-9a-fA-F]{6}\b/g;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.(tsx?|css)$/.test(name) ? [p] : [];
  });
}

describe("colours", () => {
  it("no hex colour outside the token file", () => {
    const found: string[] = [];
    for (const f of files(SRC)) {
      const rel = relative(SRC, f).replace(/\\/g, "/");
      if (ALLOWED.has(rel)) continue;
      readFileSync(f, "utf8")
        .split("\n")
        .forEach((line, i) => {
          // an element id or a URL fragment (href="#main") is not a colour
          for (const m of line.matchAll(HEX)) {
            const before = line.slice(Math.max(0, m.index! - 6), m.index);
            if (/href=["'`]$|id=["'`]$|url\(["']?$/.test(before)) continue;
            found.push(`${rel}:${i + 1}: ${m[0]}`);
          }
        });
    }
    expect(found).toEqual([]);
  });
});
