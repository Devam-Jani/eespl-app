import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";
import { inr } from "./format";

// Money shows one way everywhere: inr() in format.ts, ₹40,106.30 (Indian grouping, two decimals).
// This walks the code of every page and fails, listing file:line, on money formatted another way:
//   - a "₹" written just before a value, in JSX (₹{x}), a template (`₹${x}`) or a sum ("₹" + x):
//     inr() puts the sign in itself
//   - an Intl.NumberFormat with a currency, or fixed decimals (minimumFractionDigits) asked of
//     toLocaleString / Intl.NumberFormat: that is a money format of its own
//   - a page's own helper called money / rupees / inr...
// format.ts (where the formatters live) and tests are not scanned. A "₹" in a label ("Rate (₹)",
// "₹ per km") is not a value and passes.

const SRC = resolve(__dirname);

type Rule = "sign" | "intl" | "helper";

// The few cases that must stay: a file, a rule, how many, and why. A new one beyond the count fails.
const ALLOW: { file: string; rule: Rule; count: number; why: string }[] = [];

const SIGN_BEFORE = /₹\s*$/;
const HELPER = /^(money|rupees?|inr\w*)$/i;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.tsx?$/.test(name) && !/\.test\./.test(name) && !/\.d\.ts$/.test(name) ? [p] : [];
  });
}

/** the options object of toLocaleString(locale, { ... }) or new Intl.NumberFormat(locale, { ... }) */
function numberOptions(node: ts.Node): ts.ObjectLiteralExpression | null {
  let args: ts.NodeArray<ts.Expression> | undefined;
  if (ts.isCallExpression(node) && ts.isPropertyAccessExpression(node.expression) && node.expression.name.text === "toLocaleString") args = node.arguments;
  else if (ts.isNewExpression(node) && node.expression.getText() === "Intl.NumberFormat") args = node.arguments;
  const opts = args?.[1];
  return opts && ts.isObjectLiteralExpression(opts) ? opts : null;
}

function optionNames(opts: ts.ObjectLiteralExpression): Set<string> {
  return new Set(opts.properties.map((p) => (p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) ? p.name.text : "")));
}

function scan(rel: string, text: string): string[] {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, rel.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS);
  const found: { rule: Rule; at: string }[] = [];
  const add = (node: ts.Node, rule: Rule, what: string) => {
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
    found.push({ rule, at: `${rel}:${line}: ${what}` });
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxElement(node) || ts.isJsxFragment(node)) {
      node.children.forEach((child, i) => {
        const next = node.children[i + 1];
        if (ts.isJsxText(child) && SIGN_BEFORE.test(child.text) && next && ts.isJsxExpression(next) && next.expression) {
          add(next, "sign", `₹{${next.expression.getText()}}: use {inr(...)}`);
        }
      });
    }
    if (ts.isTemplateExpression(node)) {
      node.templateSpans.forEach((span, i) => {
        const before = i === 0 ? node.head.text : node.templateSpans[i - 1].literal.text;
        if (SIGN_BEFORE.test(before)) add(span, "sign", `\`₹\${${span.expression.getText()}}\`: use \${inr(...)}`);
      });
    }
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = node.left;
      if ((ts.isStringLiteral(left) || ts.isNoSubstitutionTemplateLiteral(left)) && SIGN_BEFORE.test(left.text) && !ts.isStringLiteralLike(node.right)) {
        add(node, "sign", `"₹" + ${node.right.getText()}: use inr(...)`);
      }
    }
    const opts = numberOptions(node);
    if (opts) {
      const names = optionNames(opts);
      if (names.has("currency") || opts.getText().includes('"currency"')) add(node, "intl", "a currency number format: use inr()");
      else if (names.has("minimumFractionDigits")) add(node, "intl", "fixed decimals (minimumFractionDigits), a money format: use inr()");
    }
    const fn = ts.isFunctionDeclaration(node) || (ts.isVariableDeclaration(node) && !!node.initializer && (ts.isArrowFunction(node.initializer) || ts.isFunctionExpression(node.initializer)));
    if (fn && node.name && ts.isIdentifier(node.name) && HELPER.test(node.name.text)) {
      add(node, "helper", `a money helper of its own (${node.name.text}): use inr() from format.ts`);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  // an allowed case passes while the file has no more of that rule than the allowlist says
  return found
    .filter((f) => {
      const ok = ALLOW.find((a) => a.file === rel && a.rule === f.rule);
      return !ok || found.filter((g) => g.rule === f.rule).length > ok.count;
    })
    .map((f) => f.at);
}

describe("money format", () => {
  it("shows two decimals in Indian grouping", () => {
    expect(inr("40106.3")).toBe("₹40,106.30");
    expect(inr(1234567)).toBe("₹12,34,567.00");
    expect(inr(null)).toBe("—");
  });

  it("finds money formatted another way", () => {
    const page = [
      "const money = (v: string) => `₹ ${Number(v).toLocaleString(\"en-IN\", { minimumFractionDigits: 2 })}`;",
      "const f = new Intl.NumberFormat(\"en-IN\", { style: \"currency\", currency: \"INR\" });",
      "const s = \"₹\" + total;",
      "export const A = ({ x }: { x: string }) => <td>₹{x} · Rate (₹) · ₹ per {x} · {inr(x)}</td>;",
    ].join("\n");
    const at = scan("page.tsx", page).map((f) => f.replace(/: .*/, ""));
    expect(at).toEqual(["page.tsx:1", "page.tsx:1", "page.tsx:1", "page.tsx:2", "page.tsx:3", "page.tsx:4"]);
  });

  it("every page formats money with inr()", () => {
    const found: string[] = [];
    for (const f of files(SRC)) {
      const rel = relative(SRC, f).replace(/\\/g, "/");
      if (rel === "format.ts") continue;
      found.push(...scan(rel, readFileSync(f, "utf8")));
    }
    expect(found).toEqual([]);
  });
});
