import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import ts from "typescript";
import { describe, expect, it } from "vitest";

// Every page builds from the shared components (ui/components.tsx, ui/Table.tsx, ui/Overlay.tsx).
// This walks the JSX of each page and fails, listing file:line, on markup from before them:
//   - a raw <button> with the old "btn" classes (use <Button variant size>), or those classes typed out
//     on a link, a file input's label or a <summary> (use className={buttonClass({ ... })})
//   - <label className="field"> (use <Field label>), or a div/fieldset with it (<Field as="div">)
//   - an element with the "card" class (use <Card>, as="div" | "article" | "aside" | "form" | "details")
//   - a raw <table> without the shared table class (use <Table>, or className="table" on a line grid)
//   - an <input>/<select>/<textarea> outside a <Field>/<Select>/<DateField>
//   - a bare file input (the browser's "Choose File"): use <FilePicker> (one hidden, or held inside a
//     page's own <label> button such as the camera tile, is not bare)
//   - a colour in an inline style={{ ... }} (use a class on the CSS variables)
// The components themselves (src/ui/**) and tests are not pages and are not scanned.

const SRC = resolve(__dirname, "..");

type Rule = "button" | "field" | "card" | "table" | "input" | "file" | "style";

// The few cases that must stay: a file, a rule, how many, and why. A new one beyond the count fails.
// Keep it small; never skip a whole file.
const ALLOW: { file: string; rule: Rule; count: number; why: string }[] = [];

const NOT_TEXT = new Set(["checkbox", "radio", "file", "hidden", "range", "color"]);
const COLOUR_PROPS = new Set(["color", "background", "backgroundColor", "borderColor", "fill", "stroke", "outlineColor"]);
const FIELD_PARENTS = new Set(["Field", "Select", "DateField"]);
// the shared button classes: "btn" and its variants (a page's own "selfie-btn" or "big-btn" is not one)
const BTN = /(?<![\w-])btn(-(primary|secondary|ghost|danger|small|block|icon))?(?![\w-])/;

function files(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) return files(p);
    return /\.tsx$/.test(name) && !/\.test\./.test(name) ? [p] : [];
  });
}

type Tag = ts.JsxOpeningElement | ts.JsxSelfClosingElement;

function attr(tag: Tag, name: string): ts.JsxAttribute | undefined {
  return tag.attributes.properties.find((p): p is ts.JsxAttribute => ts.isJsxAttribute(p) && p.name.getText() === name);
}

/** the class text an attribute can produce: a string literal's value, or the source of an expression */
function classText(tag: Tag): string | null {
  const a = attr(tag, "className");
  if (!a || !a.initializer) return null;
  if (ts.isStringLiteral(a.initializer)) return a.initializer.text;
  return a.initializer.getText();
}

/** has the class token `word` (a whole class: "card" but not "card-head" or "cards") */
function hasClass(text: string | null, word: string): boolean {
  if (!text) return false;
  return new RegExp(`(?<![\\w-])${word}(?![\\w-])`).test(text);
}

function insideField(node: ts.Node): boolean {
  for (let p = node.parent; p; p = p.parent) {
    if (ts.isJsxElement(p) && FIELD_PARENTS.has(p.openingElement.tagName.getText())) return true;
  }
  return false;
}

/** directly inside a page's own <label> (a styled button around the input), not a <Field> */
function inOwnLabel(node: ts.Node): boolean {
  const p = node.parent;
  return ts.isJsxElement(p) && p.openingElement.tagName.getText() === "label" && !hasClass(classText(p.openingElement), "field");
}

/** the object of style={{ ... }}, also when cast (style={{ ... } as CSSProperties}) */
function styleObject(e: ts.Expression | undefined): ts.ObjectLiteralExpression | null {
  while (e && (ts.isAsExpression(e) || ts.isParenthesizedExpression(e) || ts.isSatisfiesExpression(e))) e = e.expression;
  return e && ts.isObjectLiteralExpression(e) ? e : null;
}

function scan(rel: string, text: string): string[] {
  const sf = ts.createSourceFile(rel, text, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);
  const found: { rule: Rule; at: string }[] = [];
  const add = (node: ts.Node, rule: Rule, what: string) => {
    const line = sf.getLineAndCharacterOfPosition(node.getStart(sf)).line + 1;
    found.push({ rule, at: `${rel}:${line}: ${what}` });
  };
  const visit = (node: ts.Node) => {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tag = node.tagName.getText();
      const cls = classText(node);
      if (tag === "button" && BTN.test(cls ?? "")) add(node, "button", "raw <button> with btn classes: use <Button>");
      else if (BTN.test(cls ?? "")) add(node, "button", `<${tag}> with btn classes typed out: use className={buttonClass({ ... })}`);
      if ((tag === "label" || tag === "div" || tag === "fieldset") && hasClass(cls, "field")) add(node, "field", `<${tag} className="field">: use <Field>`);
      if (tag !== "Card" && hasClass(cls, "card")) add(node, "card", `<${tag} className="card">: use <Card>`);
      if (tag === "table" && !hasClass(cls, "table")) add(node, "table", "<table> without the shared table class: use <Table> or className=\"table\"");
      if (tag === "input" || tag === "select" || tag === "textarea") {
        const type = attr(node, "type")?.initializer;
        const kind = type && ts.isStringLiteral(type) ? type.text : "";
        if (!(tag === "input" && NOT_TEXT.has(kind)) && !insideField(node)) add(node, "input", `<${tag}> outside a <Field>`);
        if (tag === "input" && kind === "file" && !attr(node, "hidden") && !inOwnLabel(node)) add(node, "file", "a bare file input: use <FilePicker>");
      }
      const style = attr(node, "style")?.initializer;
      const obj = style && ts.isJsxExpression(style) ? styleObject(style.expression) : null;
      if (obj) {
        for (const p of obj.properties) {
          const name = p.name && (ts.isIdentifier(p.name) || ts.isStringLiteral(p.name)) ? p.name.text : "";
          if (COLOUR_PROPS.has(name)) add(p, "style", `inline colour "${name}" in style: use a class on the CSS variables`);
        }
      }
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

describe("old markup", () => {
  it("every page uses the shared components", () => {
    const found: string[] = [];
    for (const f of files(SRC)) {
      const rel = relative(SRC, f).replace(/\\/g, "/");
      if (rel.startsWith("ui/")) continue;
      found.push(...scan(rel, readFileSync(f, "utf8")));
    }
    expect(found).toEqual([]);
  });
});
