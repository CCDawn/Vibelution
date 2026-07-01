/**
 * Style-migration damage audit.
 *
 * Compares each route's createVuiStyleMap extensions (`*.styles.ts`) against the
 * pre-migration original CSS module (recovered from git at REF), and flags the
 * four systematic damage patterns from the lossy `ccf0cb5a` migration:
 *   1. icon-stacking  — original styled `.key a` / `.key [data-vui]` as inline-flex,
 *                        but the extension dropped the `[&_a]` / `[&_[data-vui]` rule.
 *   2. grid-collapse  — original was `display:grid` with columns, extension has no grid-cols.
 *   3. flex->grid     — original was `display:flex`, extension mistranslated to grid-cols.
 *   4. sub-14px       — extension hard-codes `text-[0.NNrem]` below the 14px floor.
 *
 * Read-only. Run: node web/scripts/audit-style-migration.mjs
 */
import { readFileSync, existsSync } from "node:fs";
import { execSync } from "node:child_process";

const REF = process.env.AUDIT_REF || "ccf0cb5a~1";
const ROUTES_DIR = "web/src/routes";

// Routes that have a styles.ts AND had an original .module.css at REF.
const ROUTES = [
  "TeamsRoute", "MemoryRoute", "ChatCodingRoute", "LogsRoute",
  "ToolsRoute", "EvolutionRoute", "ResearchFlowCanvasRoute", "ResearchRoute",
];

function gitShow(path) {
  try {
    return execSync(`git show ${REF}:${path}`, { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] });
  } catch {
    return null;
  }
}

/** Extract { key: "class string" } from the createVuiStyleMap extensions object. */
function parseStyleExtensions(src) {
  const map = {};
  // Match `    keyName:` then a run of string literals (possibly concatenated / multi-line).
  const re = /\n {4}([A-Za-z0-9_]+):\s*((?:"(?:[^"\\]|\\.)*"\s*\+?\s*)+),?(?=\n)/g;
  let m;
  while ((m = re.exec(src))) {
    const key = m[1];
    const value = m[2]
      .split(/"\s*\+\s*"/).join("") // join concatenations
      .replace(/^"|"$/g, "")
      .replace(/\\"/g, '"');
    map[key] = value;
  }
  return map;
}

/**
 * Parse original CSS into per-class facts:
 *   base[class] = { display, hasGridCols }
 *   descendantInlineFlex[class] = true  (had `.class a`/`[data-vui] { inline-flex }`)
 */
function parseOriginalCss(css) {
  const base = {};
  const descendantInlineFlex = {};
  // crude rule split
  const rules = css.split("}");
  for (const chunk of rules) {
    const idx = chunk.indexOf("{");
    if (idx === -1) continue;
    const selectorPart = chunk.slice(0, idx);
    const body = chunk.slice(idx + 1);
    const display = /display:\s*([a-z-]+)/.exec(body)?.[1] || null;
    const hasGridCols = /grid-template-columns\s*:/.test(body);
    const isInlineFlex = /display:\s*inline-flex/.test(body);
    for (const sel of selectorPart.split(",")) {
      const s = sel.trim();
      // base class rule: `.name` (single class, no descendant)
      const baseMatch = /^\.([A-Za-z0-9_]+)\s*$/.exec(s);
      if (baseMatch) {
        base[baseMatch[1]] = { display, hasGridCols };
        continue;
      }
      // descendant anchor/native-button under a class
      const descMatch = /^\.([A-Za-z0-9_]+)\s+(a|\[data-vui[^\]]*\])\b/.exec(s);
      if (descMatch && isInlineFlex) {
        descendantInlineFlex[descMatch[1]] = true;
      }
    }
  }
  return { base, descendantInlineFlex };
}

/**
 * Replicates createVuiStyleMap's key-name → default-display classification so we
 * can judge grid-collapse severity:
 *   "autofit" — key gets a responsive auto-fit grid default → NOT collapsed,
 *               only original column-count fidelity is lost (cosmetic).
 *   "collapse-risk" — key gets single-col grid / panel / row / nothing → a
 *               multi-column original genuinely collapses (real bug).
 */
function defaultKind(key) {
  const words = key.replace(/([a-z])([A-Z])/g, "$1 $2").toLowerCase().split(/[^a-z0-9]+/);
  const has = (arr) => arr.some((w) => words.includes(w));
  if (has(["grid", "cards", "columns", "stats", "metrics", "subgrid"])) return "autofit";
  return "collapse-risk";
}

function subReadableFonts(value) {
  const found = [];
  const re = /text-\[(\d*\.?\d+)rem\]/g;
  let m;
  while ((m = re.exec(value))) {
    if (parseFloat(m[1]) < 0.875) found.push(m[0]);
  }
  return found;
}

const summary = [];
for (const route of ROUTES) {
  const stylesPath = `${ROUTES_DIR}/${route}.styles.ts`;
  const cssOrig = gitShow(`${ROUTES_DIR}/${route}.module.css`);
  if (!existsSync(stylesPath) || !cssOrig) {
    summary.push({ route, note: "skip (missing styles.ts or original css)" });
    continue;
  }
  const ext = parseStyleExtensions(readFileSync(stylesPath, "utf8"));
  const { base, descendantInlineFlex } = parseOriginalCss(cssOrig);
  // Is `styles.<key>` still referenced in the route .tsx? (dead-key filter)
  const tsxPath = `${ROUTES_DIR}/${route}.tsx`;
  const tsx = existsSync(tsxPath) ? readFileSync(tsxPath, "utf8") : "";
  const isUsed = (key) => new RegExp(`styles\\.${key}\\b`).test(tsx) || new RegExp(`styles\\.\\w*\\[\`?${key}`).test(tsx);

  const findings = { iconStacking: [], gridCollapse: [], flexToGrid: [], sub14: [] };

  // key set = union of keys present in styles.ts extensions and original base classes
  const keys = new Set([...Object.keys(ext), ...Object.keys(base)]);
  for (const key of keys) {
    const value = ext[key]; // may be undefined (default-only key)
    const orig = base[key];

    // 1. icon-stacking: original styled descendant a/native-button inline-flex, ext lacks it
    if (descendantInlineFlex[key] && isUsed(key)) {
      const hasFix = value && (/\[&_a\]/.test(value) || /\[&_\[data-vui/.test(value));
      if (!hasFix) findings.iconStacking.push(key);
    }
    // 2. grid-collapse: original grid+cols, ext has no grid-cols/grid-template/!grid
    if (orig && orig.display === "grid" && orig.hasGridCols && isUsed(key)) {
      const hasCols = value && /(grid-cols-|grid-template)/.test(value);
      if (!hasCols) findings.gridCollapse.push(`${key}${defaultKind(key) === "collapse-risk" ? "!" : ""}`);
    }
    // 3. flex->grid: original flex, ext uses grid-cols
    if (orig && orig.display === "flex" && value && /grid-cols-/.test(value) && isUsed(key)) {
      findings.flexToGrid.push(key);
    }
    // 4. sub-14px
    if (value) {
      const s = subReadableFonts(value);
      if (s.length) findings.sub14.push(`${key}(${s.join(",")})`);
    }
  }

  summary.push({ route, findings });
}

// Report
let total = 0;
for (const row of summary) {
  if (row.note) { console.log(`\n### ${row.route}: ${row.note}`); continue; }
  const f = row.findings;
  const count = f.iconStacking.length + f.gridCollapse.length + f.flexToGrid.length + f.sub14.length;
  total += count;
  console.log(`\n### ${row.route}  (${count} findings)`);
  if (f.iconStacking.length) console.log(`  icon-stacking (${f.iconStacking.length}): ${f.iconStacking.join(", ")}`);
  if (f.gridCollapse.length) console.log(`  grid-collapse (${f.gridCollapse.length}): ${f.gridCollapse.join(", ")}`);
  if (f.flexToGrid.length)   console.log(`  flex->grid   (${f.flexToGrid.length}): ${f.flexToGrid.join(", ")}`);
  if (f.sub14.length)        console.log(`  sub-14px     (${f.sub14.length}): ${f.sub14.join(", ")}`);
}
console.log(`\n=== TOTAL findings: ${total} across ${ROUTES.length} routes (ref ${REF}) ===`);
