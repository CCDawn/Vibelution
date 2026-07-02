/**
 * Mechanical CSS-Module → explicit Tailwind class-map converter (2026-07-02
 * refined-target workstream: kill the last scoped-CSS styling system).
 *
 * Each CSS declaration becomes a Tailwind arbitrary property `[prop:value]`
 * (spaces → underscores) which emits byte-identical CSS — the same house style
 * the baked route maps already use. A tiny curated set of unambiguous values is
 * mapped to real utilities; everything else stays arbitrary so there are no
 * human translation errors.
 *
 * Selector handling:
 *   .a { }        → key a (base)
 *   .a, .b { }    → keys a and b
 *   .a:hover { }  → key a, variant `hover:`
 *   .a .b { }     → key b FLATTENED (b is applied directly in the JSX, always
 *                   inside a; specificity drops one class). Conflicts (same b
 *                   flattened from >1 ancestor with differing bodies) reported.
 *   .a strong { } → key a, variant `[&_strong]:`
 *   .a>.b / .a+.b → treated as descendant class → flatten onto b
 *   @media(max-width:N){…} → variant `max-[Npx]:`
 * Same (variant, property) appearing twice keeps the LAST (CSS cascade).
 *
 * Usage: node scripts/convert-css-module.mjs <RouteName> [--write]
 */
import { readFileSync, writeFileSync } from "node:fs";

const name = process.argv[2];
if (!name) { console.error("usage: convert-css-module.mjs <RouteName> [--write]"); process.exit(2); }
const write = process.argv.includes("--write");
const cssPath = `src/routes/${name}.module.css`;
const outPath = `src/routes/${name}.styles.ts`;
const css = readFileSync(cssPath, "utf8").replace(/\/\*[\s\S]*?\*\//g, "");

// --- brace-aware tokenizer: yields {selectorGroup, body, mediaVariant} ---
function parseBlock(text, mediaVariant, out) {
  let i = 0;
  const n = text.length;
  while (i < n) {
    // skip whitespace
    while (i < n && /\s/.test(text[i])) i++;
    if (i >= n) break;
    // read prelude up to '{'
    let start = i;
    let depthParen = 0;
    while (i < n && !(text[i] === "{" && depthParen === 0)) {
      if (text[i] === "(") depthParen++;
      else if (text[i] === ")") depthParen--;
      i++;
    }
    if (i >= n) break;
    const prelude = text.slice(start, i).trim();
    // read balanced { ... }
    i++; // past '{'
    let bodyStart = i, depth = 1;
    while (i < n && depth > 0) {
      if (text[i] === "{") depth++;
      else if (text[i] === "}") depth--;
      if (depth === 0) break;
      i++;
    }
    const inner = text.slice(bodyStart, i);
    i++; // past matching '}'
    if (prelude.startsWith("@media")) {
      const m = prelude.match(/max-width:\s*(\d+)px/);
      const mv = m ? `max-[${m[1]}px]:` : "";
      parseBlock(inner, (mediaVariant || "") + mv, out);
    } else if (prelude.startsWith("@")) {
      // @keyframes/@supports etc — skip (none expected in these files)
    } else {
      out.push({ selectorGroup: prelude, body: inner.trim(), mediaVariant: mediaVariant || "" });
    }
  }
}

// --- declaration → Tailwind ---
const DISPLAY = { grid: "grid", flex: "flex", block: "block", none: "hidden", "inline-flex": "inline-flex", "inline-grid": "inline-grid", "inline-block": "inline-block", inline: "inline", contents: "contents" };
function arb(prop, value) {
  const v = value.trim().replace(/\\/g, "").replace(/_/g, "\\_").replace(/\s+/g, "_");
  return `[${prop}:${v}]`;
}
function declToTw(prop, value) {
  const v = value.trim();
  if (prop === "display" && DISPLAY[v]) return DISPLAY[v];
  if (prop === "min-width" && v === "0") return "min-w-0";
  if (prop === "min-height" && v === "0") return "min-h-0";
  return arb(prop, v);
}

// --- selector classification ---
function classify(selector) {
  const sel = selector.trim();
  const parts = sel.split(/\s*[>+~]\s*|\s+/).filter(Boolean);
  if (parts.length === 1) {
    const p = parts[0];
    const cls = p.match(/^\.([A-Za-z0-9_]+)/);
    if (!cls) return null;
    const pseudo = p.slice(cls[0].length).match(/^:([a-z-]+)$/);
    return { key: cls[1], variant: pseudo ? `${pseudo[1]}:` : "" };
  }
  const first = parts[0].match(/^\.([A-Za-z0-9_]+)/);
  if (!first) return null;
  const last = parts[parts.length - 1];
  const lastCls = last.match(/^\.([A-Za-z0-9_]+)(:[a-z-]+)?$/);
  if (lastCls) {
    // descendant class → flatten onto the child key
    return { key: lastCls[1], variant: lastCls[2] ? `${lastCls[2].slice(1)}:` : "", flattenedFrom: first[1] };
  }
  // element/attr descendant → variant on ancestor
  const em = last.match(/^([a-z]+|\[[^\]]+\])(:[a-z-]+)?$/);
  if (em) {
    const pseudo = em[2] ? `${em[2].slice(1)}:` : "";
    return { key: first[1], variant: `[&_${em[1]}]:${pseudo}` };
  }
  return null;
}

// key → ordered [{variant, prop, tw}]
const entries = {};
const flattenSources = {};
function classifyAndPush(r) {
  for (const selector of r.selectorGroup.split(",")) {
    const c = classify(selector);
    if (!c) continue;
    const variant = (r.mediaVariant || "") + c.variant;
    for (const decl of r.body.split(";")) {
      const idx = decl.indexOf(":");
      if (idx === -1) continue;
      const prop = decl.slice(0, idx).trim();
      const value = decl.slice(idx + 1).trim();
      if (!prop || !value || prop.startsWith("@")) continue;
      const tw = declToTw(prop, value);
      (entries[c.key] ??= []).push({ variant, prop, tw });
    }
    if (c.flattenedFrom) (flattenSources[c.key] ??= new Set()).add(c.flattenedFrom);
  }
}

const rules = [];
parseBlock(css, "", rules);
for (const r of rules) classifyAndPush(r);

// cascade-dedupe: keep LAST occurrence of each (variant, prop)
const map = {};
for (const [key, list] of Object.entries(entries)) {
  const lastIndex = new Map();
  list.forEach((e, i) => lastIndex.set(`${e.variant}||${e.prop}`, i));
  const kept = list.filter((e, i) => lastIndex.get(`${e.variant}||${e.prop}`) === i);
  map[key] = kept.map((e) => e.variant ? e.tw.split(" ").map((c) => e.variant + c).join(" ") : e.tw).join(" ");
}

const conflicts = Object.entries(flattenSources).filter(([, s]) => s.size > 1).map(([k]) => k);
const report = [
  `# convert-css-module ${name}`,
  `keys: ${Object.keys(map).length}`,
  `flatten-conflicts (same class flattened from >1 ancestor — MANUAL REVIEW): ${conflicts.length ? conflicts.join(", ") : "none"}`,
];

const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/;
const lines = [
  "// Explicit Tailwind style map — converted from the former",
  `// ${name}.module.css by web/scripts/convert-css-module.mjs (2026-07-02 refined`,
  "// target: one styling system). Declarations are Tailwind arbitrary properties",
  "// emitting byte-identical CSS; descendant .a .b rules were flattened onto the",
  "// child key. Edit values directly.",
  "const styles: Record<string, string> = {",
];
for (const key of Object.keys(map).sort()) {
  lines.push(`  ${IDENT.test(key) ? key : JSON.stringify(key)}:`);
  lines.push(`    ${JSON.stringify(map[key])},`);
}
lines.push("};", "", "export default styles;", "");
const output = lines.join("\n");

if (write) {
  writeFileSync(outPath, output);
  console.error(report.join("\n") + `\nwrote ${outPath}`);
} else {
  console.error(report.join("\n"));
  console.log(output.slice(0, 3000));
  console.error(`\n[dry-run] ${Object.keys(map).length} keys; pass --write to emit`);
}
