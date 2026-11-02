import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

// We have not built an ERP: the word never reaches a person (sidebar, login, tab title, any page).
// The product's name and tag come from the backend's app/branding.py (GET /api/ops/mode).
const ROOT = resolve(__dirname, "../..");
const ERP = /\bERP\b/i;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return name === "testdata" ? [] : files(p);
    return /\.(tsx?|css|html|json)$/.test(name) ? [p] : [];
  });
}

describe("no ERP", () => {
  it("appears in no page, component, stylesheet or index.html", () => {
    const found = [...files(join(ROOT, "src")), join(ROOT, "index.html")]
      .filter((f) => !f.endsWith("noerp.test.ts"))
      .flatMap((f) => readFileSync(f, "utf8").split("\n").flatMap((line, i) => (ERP.test(line) ? [`${relative(ROOT, f)}:${i + 1}`] : [])));
    expect(found).toEqual([]);
  });

  it("the sidebar and the login page take the name and tag from the branding, not a literal", () => {
    for (const f of ["src/components/Layout.tsx", "src/pages/Login.tsx"]) {
      const text = readFileSync(join(ROOT, f), "utf8");
      expect(text).toContain("brand?.product_tag");
      expect(text).not.toMatch(/<small>[^<{]+<\/small>/);
    }
  });
});
