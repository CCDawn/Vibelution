/**
 * Wave 8C: extract single-owner production keys from ChatCodingRoute.styles
 * into local panel style maps, then prune dead + extracted keys from the route map.
 *
 * Usage (from web/): node scripts/extract-chat-panel-styles.mjs [--dry-run]
 */
import { readFileSync, writeFileSync, readdirSync, existsSync } from "node:fs";
import path from "node:path";

const dryRun = process.argv.includes("--dry-run");
const routeStylesPath = "src/routes/ChatCodingRoute.styles.ts";
const routeStylesSrc = readFileSync(routeStylesPath, "utf8");

const TARGETS = [
  {
    file: "src/routes/chat/CacheDetailDialog.tsx",
    stylesOut: "src/routes/chat/CacheDetailDialog.styles.ts",
    importPath: "./CacheDetailDialog.styles",
  },
  {
    file: "src/routes/chat/TokenCoreStatusPanel.tsx",
    stylesOut: "src/routes/chat/TokenCoreStatusPanel.styles.ts",
    importPath: "./TokenCoreStatusPanel.styles",
  },
  {
    file: "src/routes/chat/ChatConversationIndexRail.tsx",
    stylesOut: "src/routes/chat/ChatConversationIndexRail.styles.ts",
    importPath: "./ChatConversationIndexRail.styles",
  },
  {
    file: "src/routes/chat/ChatStatusRail.tsx",
    stylesOut: "src/routes/chat/ChatStatusRail.styles.ts",
    importPath: "./ChatStatusRail.styles",
  },
];

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

// Parse style blocks from route map
const mapStart = routeStylesSrc.indexOf("const styles: Record<string, string> = {");
const mapEnd = routeStylesSrc.lastIndexOf("\n};");
if (mapStart < 0 || mapEnd < 0) {
  console.error("Could not locate ChatCodingRoute styles map");
  process.exit(1);
}
const mapBody = routeStylesSrc.slice(
  mapStart + "const styles: Record<string, string> = {".length,
  mapEnd,
);
const lines = mapBody.split("\n");
const blocks = [];
let current = null;
for (const line of lines) {
  // Some legacy keys lost indent (e.g. `layout:` at column 0). Accept 0–2 spaces.
  const keyMatch = line.match(/^ {0,2}([a-zA-Z][a-zA-Z0-9_]*)\s*:/);
  if (keyMatch) {
    if (current) blocks.push(current);
    // Normalize to 2-space indent in output
    const normalized = line.replace(/^ {0,2}/, "  ");
    current = { key: keyMatch[1], lines: [normalized] };
  } else if (current) {
    current.lines.push(line);
  }
}
if (current) blocks.push(current);
const byKey = new Map(blocks.map((b) => [b.key, b]));
const allKeys = blocks.map((b) => b.key);

// Importer usage
const used = new Map(); // key -> Set files
const dynPrefixes = new Set();
for (const file of walk("src")) {
  if (path.resolve(file) === path.resolve(routeStylesPath)) continue;
  const text = readFileSync(file, "utf8");
  const m = /import\s+(\w+)\s+from\s+"[^"]*ChatCodingRoute\.styles"/.exec(text);
  if (!m) continue;
  const alias = m[1];
  for (const sm of text.matchAll(new RegExp(`\\b${alias}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, "g"))) {
    const k = sm[1];
    if (!used.has(k)) used.set(k, new Set());
    used.get(k).add(file.replace(/\\/g, "/"));
  }
  for (const dm of text.matchAll(new RegExp(`\\b${alias}\\[\\\`([A-Za-z0-9_$]*?)\\$\\{`, "g"))) {
    if (dm[1]) dynPrefixes.add(dm[1]);
  }
}
const allImp = walk("src")
  .filter((f) => {
    try {
      return readFileSync(f, "utf8").includes("ChatCodingRoute.styles");
    } catch {
      return false;
    }
  })
  .map((f) => readFileSync(f, "utf8"))
  .join("\n");

function isDead(k) {
  if (used.has(k)) return false;
  if ([...dynPrefixes].some((p) => k.startsWith(p))) return false;
  const us = k.indexOf("_");
  if (us > 0 && allImp.includes(`${k.slice(0, us)}_`)) return false;
  return true;
}

// Dynamic keys that belong with a target: any key matching dyn prefixes used in that file
function keysForTarget(targetFile, dynPrefixesForFile = []) {
  const norm = targetFile.replace(/\\/g, "/");
  const owned = new Set();
  for (const k of allKeys) {
    const files = [...(used.get(k) || [])].filter((f) => !f.includes(".test."));
    if (files.length === 1 && files[0] === norm) owned.add(k);
  }
  // Pull dyn-prefix keys used only by this panel (or unused outside tests).
  for (const prefix of dynPrefixesForFile) {
    for (const k of allKeys) {
      if (!k.startsWith(prefix)) continue;
      const files = [...(used.get(k) || [])].filter((f) => !f.includes(".test."));
      if (!files.length || (files.length === 1 && files[0] === norm)) {
        owned.add(k);
      }
    }
  }
  return [...owned];
}

// Collect recipe tokens from a block text
const RECIPE_SURFACE = [
  "vuiFlatPanelClass",
  "vuiGlassPanelClass",
  "vuiOpaqueRowClass",
  "vuiRailFillClass",
  "vuiStateCoolInfoClass",
  "vuiStateCoolSoftClass",
  "vuiStateDangerSoftClass",
  "vuiStateSelectedRowClass",
  "vuiStateSelectedRowFillClass",
  "vuiStateSuccessSoftClass",
  "vuiStateWarmSoftClass",
  "vuiStateWarningSoftClass",
  "vuiChatFillClass",
  "vuiWorkspaceFillClass",
];
const RECIPE_CHROME = ["vuiControlPillClass", "vuiControlQuietClass"];

function buildStylesFile(keys, comment) {
  const kept = keys.map((k) => byKey.get(k)).filter(Boolean);
  const body = kept
    .map((b) => {
      let t = b.lines.join("\n").replace(/\n+$/, "");
      if (!/,\s*$/.test(t)) t += ",";
      return t;
    })
    .join("\n");
  const chrome = RECIPE_CHROME.filter((n) => body.includes(n));
  const surface = RECIPE_SURFACE.filter((n) => body.includes(n));
  let out = `// ${comment}\n`;
  if (chrome.length) {
    out += `\nimport {\n${chrome.map((n) => `  ${n},`).join("\n")}\n} from "../../design/vuiChromeRecipes";\n`;
  }
  if (surface.length) {
    out += `\nimport {\n${surface.map((n) => `  ${n},`).join("\n")}\n} from "../../design/vuiSurfaceRecipes";\n`;
  }
  out += `\nconst styles = {\n${body}\n} as const;\n\nexport default styles;\n`;
  return out;
}

const extractedKeys = new Set();
const report = [];

for (const target of TARGETS) {
  const tsx = readFileSync(target.file, "utf8");
  const dynRefs = [...new Set([...tsx.matchAll(/styles\[`([A-Za-z0-9_]*?)\$\{/g)].map((m) => m[1]))];
  const owned = keysForTarget(target.file, dynRefs);
  owned.sort();
  if (!owned.length) {
    report.push({ target: target.file, owned: 0, skipped: true });
    continue;
  }
  for (const k of owned) extractedKeys.add(k);

  // Shared keys still needed from route? (TokenCore uses leftBlock etc. which are multi/shared)
  const allRefs = [...tsx.matchAll(/styles\.([A-Za-z0-9_]+)/g)].map((m) => m[1]);
  const sharedStill = [...new Set(allRefs)].filter((k) => !owned.includes(k) && byKey.has(k));

  report.push({
    target: target.file,
    owned: owned.length,
    sharedStill,
    dynRefs,
    sample: owned.slice(0, 12),
  });

  if (dryRun) continue;

  const stylesContent = buildStylesFile(
    owned,
    `Wave 8C: extracted from ChatCodingRoute.styles for ${path.basename(target.file)}`,
  );
  writeFileSync(target.stylesOut, stylesContent);

  // Rewrite imports in the panel file
  let next = tsx;
  if (sharedStill.length) {
    // dual import: local styles + route styles for shared chrome
    next = next.replace(
      /import styles from ["']\.\.\/ChatCodingRoute\.styles["'];/,
      `import routeStyles from "../ChatCodingRoute.styles";\nimport styles from "${target.importPath}";`,
    );
    // Rewrite sharedStill references styles.X -> routeStyles.X
    for (const k of sharedStill) {
      next = next.replaceAll(`styles.${k}`, `routeStyles.${k}`);
    }
  } else {
    next = next.replace(
      /import styles from ["']\.\.\/ChatCodingRoute\.styles["'];/,
      `import styles from "${target.importPath}";`,
    );
  }
  writeFileSync(target.file, next);
}

// Dead keys: leave on route map in this knife (layout tests still contract many
// only-test keys). A later prune pass can drop them with retargeted tests.
const dead = allKeys.filter(isDead);

// Rebuild route styles without extracted panel-owned keys only
const keepBlocks = blocks.filter((b) => !extractedKeys.has(b.key));
const keepBody = keepBlocks
  .map((b) => {
    let t = b.lines.join("\n").replace(/\n+$/, "");
    if (!/,\s*$/.test(t)) t += ",";
    return t;
  })
  .join("\n");

const chrome = RECIPE_CHROME.filter((n) => keepBody.includes(n));
const surface = RECIPE_SURFACE.filter((n) => keepBody.includes(n));

let routeOut = `// ChatCodingRoute styles (Wave 8C prune + panel extraction).
// Panel-owned maps: CacheDetailDialog, TokenCoreStatusPanel, ChatConversationIndexRail, ChatStatusRail.
// Remaining keys: shell/layout shared + multi-consumer + layout-test contracts still on this map.
`;
if (chrome.length) {
  routeOut += `\nimport {\n${chrome.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiChromeRecipes";\n`;
}
if (surface.length) {
  routeOut += `\nimport {\n${surface.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiSurfaceRecipes";\n`;
}
routeOut += `\nconst styles: Record<string, string> = {\n${keepBody}\n};\n\nexport default styles;\n`;

const summary = {
  dryRun,
  before: allKeys.length,
  extracted: extractedKeys.size,
  deadLeftOnRoute: dead.length,
  after: keepBlocks.length,
  report,
};
console.log(JSON.stringify(summary, null, 2));

if (!dryRun) {
  writeFileSync(routeStylesPath, routeOut);
  console.log(`wrote ${routeStylesPath} (${allKeys.length} -> ${keepBlocks.length})`);
}
