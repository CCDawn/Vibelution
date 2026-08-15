/**
 * Wave 8D: prune ChatCodingRoute dead keys; move orphan test-contract keys
 * into panel maps; expand layout-test merge coverage.
 * Usage (from web/): node scripts/wave8d-chat-dead-prune.mjs [--dry-run]
 */
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import path from "node:path";

const dryRun = process.argv.includes("--dry-run");
const stylesPath = "src/routes/ChatCodingRoute.styles.ts";
const stylesSrc = readFileSync(stylesPath, "utf8");

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

function parseBlocks(src) {
  const mapDecl = src.match(/const styles(?::\s*[^=]+)?\s*=\s*\{/);
  if (!mapDecl || mapDecl.index == null) throw new Error("no styles map");
  const bodyStart = mapDecl.index + mapDecl[0].length;
  let mapEnd = src.lastIndexOf("} as const;");
  if (mapEnd < bodyStart) mapEnd = src.lastIndexOf("\n};");
  const body = src.slice(bodyStart, mapEnd);
  const lines = body.split("\n");
  const blocks = [];
  let current = null;
  for (const line of lines) {
    const keyMatch = line.match(/^ {0,2}([a-zA-Z][a-zA-Z0-9_]*)\s*:/);
    if (keyMatch) {
      if (current) blocks.push(current);
      current = { key: keyMatch[1], lines: [line.replace(/^ {0,2}/, "  ")] };
    } else if (current) {
      current.lines.push(line);
    }
  }
  if (current) blocks.push(current);
  return { mapDecl: mapDecl[0], mapStart: mapDecl.index, mapEnd, blocks, suffix: src.slice(mapEnd) };
}

function collectDead(src, allKeys) {
  const used = new Set();
  const dynPrefixes = new Set();
  let allImp = "";
  for (const file of walk("src")) {
    if (path.resolve(file) === path.resolve(stylesPath)) continue;
    const text = readFileSync(file, "utf8");
    const m = /import\s+(\w+)\s+from\s+"[^"]*ChatCodingRoute\.styles"/.exec(text);
    if (!m) continue;
    allImp += text + "\n";
    const alias = m[1];
    for (const sm of text.matchAll(new RegExp(`\\b${alias}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, "g"))) {
      used.add(sm[1]);
    }
    for (const dm of text.matchAll(new RegExp(`\\b${alias}\\[\\\`([A-Za-z0-9_$]*?)\\$\\{`, "g"))) {
      if (dm[1]) dynPrefixes.add(dm[1]);
    }
  }
  return allKeys.filter((k) => {
    if (used.has(k)) return false;
    if ([...dynPrefixes].some((p) => k.startsWith(p))) return false;
    const us = k.indexOf("_");
    if (us > 0 && allImp.includes(`${k.slice(0, us)}_`)) return false;
    return true;
  });
}

function appendBlocksToStylesFile(filePath, blocks, extraSurface = []) {
  if (!blocks.length) return;
  let src = readFileSync(filePath, "utf8");
  const insert = blocks
    .map((b) => {
      let t = b.lines.join("\n").replace(/\n+$/, "");
      if (!/,\s*$/.test(t)) t += ",";
      return t;
    })
    .join("\n");
  // skip already-present keys
  const missing = blocks.filter((b) => !new RegExp(`^ {0,2}${b.key}:`, "m").test(src));
  if (!missing.length) return;
  const missingInsert = missing
    .map((b) => {
      let t = b.lines.join("\n").replace(/\n+$/, "");
      if (!/,\s*$/.test(t)) t += ",";
      return t;
    })
    .join("\n");
  src = src.replace(/\n\};\n\nexport default styles;\n?$/, `\n${missingInsert}\n};\n\nexport default styles;\n`);
  for (const name of extraSurface) {
    if (missingInsert.includes(name) && !src.includes(name)) {
      src = src.replace(
        /import \{\n([\s\S]*?)\} from "\.\.\/\.\.\/design\/vuiSurfaceRecipes";/,
        (m, body) => {
          if (body.includes(name)) return m;
          const trimmed = body.trim().replace(/,?\s*$/, ",");
          return `import {\n${trimmed}\n  ${name},\n} from "../../design/vuiSurfaceRecipes";`;
        },
      );
    }
  }
  if (!dryRun) writeFileSync(filePath, src);
  console.log(`append ${missing.map((b) => b.key).join(", ")} -> ${filePath}`);
}

const parsed = parseBlocks(stylesSrc);
const allKeys = parsed.blocks.map((b) => b.key);
const byKey = new Map(parsed.blocks.map((b) => [b.key, b]));
const dead = collectDead(stylesSrc, allKeys);
const deadSet = new Set(dead);

// Move orphan test-contract keys into CacheDetail before prune
const toCache = [
  "cacheDonutShell",
  "cacheDonutStats",
  "contextCompositionSegmentCacheWrite",
  "contextCompositionSegmentCached",
  "contextCompositionSegmentExact",
  "contextCompositionSegmentMissing",
  "contextCompositionSegmentUncached",
  "contextCompositionSegmentUnused",
].map((k) => byKey.get(k)).filter(Boolean);

appendBlocksToStylesFile(
  "src/routes/chat/CacheDetailDialog.styles.ts",
  toCache,
  ["vuiStateWarmSoftClass"],
);

// Move teamTree orphans into ConversationIndexTree.styles if file exists
const teamTreeKeys = ["teamTreeChild", "teamTreeChildren", "teamTreeGroup", "teamTreeItem", "teamTreeLabelRow"]
  .map((k) => byKey.get(k))
  .filter(Boolean);
const treePath = "src/routes/ConversationIndexTree.styles.ts";
try {
  appendBlocksToStylesFile(treePath, teamTreeKeys, ["vuiOpaqueRowClass"]);
} catch {
  console.log("skip teamTree move (no ConversationIndexTree.styles?)");
}

console.log(JSON.stringify({ total: allKeys.length, dead: dead.length, dryRun }, null, 2));
if (dryRun) process.exit(0);

// Rebuild route map without dead keys
const kept = parsed.blocks.filter((b) => !deadSet.has(b.key));
const keptText = kept
  .map((b) => {
    let t = b.lines.join("\n").replace(/\n+$/, "");
    if (!/,\s*$/.test(t)) t += ",";
    return t;
  })
  .join("\n");

const CHROME = ["vuiControlPillClass", "vuiControlQuietClass"];
const SURFACE = [
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
const chrome = CHROME.filter((n) => keptText.includes(n));
const surface = SURFACE.filter((n) => keptText.includes(n));

let out = `// ChatCodingRoute styles (Wave 8D dead-key prune after 8C panel extraction).
// Removed ${dead.length} unused keys; panel/component maps own former residue.
`;
if (chrome.length) {
  out += `\nimport {\n${chrome.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiChromeRecipes";\n`;
}
if (surface.length) {
  out += `\nimport {\n${surface.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiSurfaceRecipes";\n`;
}
out += `\n${parsed.mapDecl}\n${keptText}\n`;
out += parsed.suffix.startsWith("}") || parsed.suffix.startsWith("\n}")
  ? parsed.suffix
  : "};\n\nexport default styles;\n";

writeFileSync(stylesPath, out);
console.log(`wrote ${stylesPath}: ${allKeys.length} -> ${kept.length}`);

// Patch layout test: merge ConversationIndexTree.styles
const layoutPath = "src/routes/ChatCodingRoute.layout.test.ts";
let layout = readFileSync(layoutPath, "utf8");
if (!layout.includes("ConversationIndexTree.styles")) {
  layout = layout.replace(
    /import conversationIndexTreeSource from "\.\/ConversationIndexTree\.tsx\?raw";/,
    `import conversationIndexTreeSource from "./ConversationIndexTree.tsx?raw";\nimport conversationIndexTreeStyles from "./ConversationIndexTree.styles";`,
  );
}
if (!layout.includes("conversationIndexTreeStyles")) {
  // already handled
}
if (layout.includes("Object.assign(routeStyles") && !layout.includes("conversationIndexTreeStyles")) {
  layout = layout.replace(
    /Object\.assign\(routeStyles, \{([\s\S]*?)\}\);/,
    (m, body) => `Object.assign(routeStyles, {${body}\n  ...conversationIndexTreeStyles,\n});`,
  );
} else if (!layout.includes("...conversationIndexTreeStyles")) {
  layout = layout.replace(
    /Object\.assign\(routeStyles, \{/,
    `Object.assign(routeStyles, {\n  ...conversationIndexTreeStyles,`,
  );
}
// Ensure aliases still work after cache move (overwrite with real keys from cacheDetail)
layout = layout.replace(
  /cacheDonutShell: cacheDetailStyles\.cacheDetailDonutShell,/,
  `cacheDonutShell: cacheDetailStyles.cacheDonutShell ?? cacheDetailStyles.cacheDetailDonutShell,`,
);
layout = layout.replace(
  /cacheDonutStats: cacheDetailStyles\.cacheDetailDonutLegend \?\? cacheDetailStyles\.cacheDetailSummaryGrid,/,
  `cacheDonutStats: cacheDetailStyles.cacheDonutStats ?? cacheDetailStyles.cacheDetailDonutLegend,`,
);
writeFileSync(layoutPath, layout);
console.log("patched layout test merge for ConversationIndexTree");
console.log("done");
