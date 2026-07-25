/**
 * Wave 8: surgically remove dead keys from a route style map.
 * Usage (from web/): node scripts/prune-route-style-map.mjs <RouteName> [--dry-run]
 *
 * Dead detection matches find-dead-style-keys.mjs (+ styles["key"] lookups).
 * Preserves original preamble/imports; only drops named imports unused after prune.
 */
import { readFileSync, writeFileSync, readdirSync } from "node:fs";
import path from "node:path";

const name = process.argv[2];
const dryRun = process.argv.includes("--dry-run");
if (!name) {
  console.error("Usage: node scripts/prune-route-style-map.mjs <RouteName> [--dry-run]");
  process.exit(1);
}

const stylesPath = `src/routes/${name}.styles.ts`;
const stylesSrc = readFileSync(stylesPath, "utf8");

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

const allKeys = [
  ...new Set([...stylesSrc.matchAll(/^  ([A-Za-z0-9_]+):(?:$|\s)/gm)].map((m) => m[1])),
];

const used = new Set();
const dynPrefixes = new Set();
const importerTexts = [];

for (const file of walk("src")) {
  if (path.resolve(file) === path.resolve(stylesPath)) continue;
  const text = readFileSync(file, "utf8");
  const m = new RegExp(`import\\s+(\\w+)\\s+from\\s+"[^"]*${name}\\.styles"`).exec(text);
  if (!m) continue;
  importerTexts.push(text);
  const alias = m[1];
  for (const sm of text.matchAll(new RegExp(`\\b${alias}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, "g"))) {
    used.add(sm[1]);
  }
  for (const dm of text.matchAll(new RegExp(`\\b${alias}\\[\\\`([A-Za-z0-9_$]*?)\\$\\{`, "g"))) {
    if (dm[1]) dynPrefixes.add(dm[1]);
  }
  for (const bm of text.matchAll(new RegExp(`\\b${alias}\\[['\"]([A-Za-z0-9_]+)['\"]\\]`, "g"))) {
    used.add(bm[1]);
  }
}
const allImporterText = importerTexts.join("\n");

// Keep keys listed in `as const` arrays that feed styles[styleName] helpers.
// Pattern: expectFoo("key") or for (const styleName of ["a","b"] as const)
const dynamicStyleArgs = new Set();
for (const text of importerTexts) {
  // for (const x of ["a", "b"] as const)
  for (const am of text.matchAll(/of\s*\[([^\]]+)\]\s*as\s+const/g)) {
    for (const lm of am[1].matchAll(/["']([A-Za-z][A-Za-z0-9_]*)["']/g)) {
      dynamicStyleArgs.add(lm[1]);
    }
  }
  // Array<keyof typeof styles> = [ "a", "b" ]
  for (const am of text.matchAll(/keyof typeof styles[^\]]*\]\s*=\s*\[([^\]]+)\]/g)) {
    for (const lm of am[1].matchAll(/["']([A-Za-z][A-Za-z0-9_]*)["']/g)) {
      dynamicStyleArgs.add(lm[1]);
    }
  }
  // const repeatedSurfaceStyles: Array<keyof typeof styles> = [ ... ]
  for (const am of text.matchAll(/:\s*Array<\s*keyof typeof styles\s*>\s*=\s*\[([^\]]+)\]/gs)) {
    for (const lm of am[1].matchAll(/["']([A-Za-z][A-Za-z0-9_]*)["']/g)) {
      dynamicStyleArgs.add(lm[1]);
    }
  }
  // const keys = [ ... ] as const satisfies readonly (keyof typeof styles)[]
  for (const am of text.matchAll(/=\s*\[([^\]]+)\]\s*as\s+const\s+satisfies\s+readonly\s*\(\s*keyof typeof styles\s*\)/gs)) {
    for (const lm of am[1].matchAll(/["']([A-Za-z][A-Za-z0-9_]*)["']/g)) {
      dynamicStyleArgs.add(lm[1]);
    }
  }
}

const dead = allKeys.filter((k) => {
  if (used.has(k)) return false;
  if (dynamicStyleArgs.has(k)) return false;
  if ([...dynPrefixes].some((p) => k.startsWith(p))) return false;
  const us = k.indexOf("_");
  if (us > 0 && allImporterText.includes(`${k.slice(0, us)}_`)) return false;
  return true;
});
const deadSet = new Set(dead);

const mapStart = stylesSrc.indexOf("const styles = {");
const mapEnd = stylesSrc.lastIndexOf("} as const;");
if (mapStart < 0 || mapEnd < 0) {
  console.error("Could not locate `const styles = { ... } as const;`");
  process.exit(1);
}

const preamble = stylesSrc.slice(0, mapStart);
const mapBody = stylesSrc.slice(mapStart + "const styles = {".length, mapEnd);
const suffix = stylesSrc.slice(mapEnd);

const lines = mapBody.split("\n");
const blocks = [];
let current = null;
let leading = [];

for (const line of lines) {
  const keyMatch = line.match(/^  ([a-zA-Z][a-zA-Z0-9_]*)\s*:/);
  const isComment = /^\s*\/\//.test(line);
  const isBlank = line.trim() === "";

  if (keyMatch) {
    if (current) blocks.push(current);
    current = { key: keyMatch[1], lines: [...leading, line] };
    leading = [];
  } else if (current) {
    const last = [...current.lines].reverse().find((l) => l.trim() !== "");
    const finished = last && /,\s*$/.test(last);
    if (finished && (isComment || isBlank)) {
      if (isComment) leading.push(line);
    } else {
      current.lines.push(line);
    }
  } else if (isComment) {
    leading.push(line);
  }
}
if (current) blocks.push(current);

const keptBlocks = blocks.filter((b) => !deadSet.has(b.key));
const removed = blocks.filter((b) => deadSet.has(b.key)).map((b) => b.key);

let mapOut = "const styles = {\n";
for (const block of keptBlocks) {
  let text = block.lines.join("\n").replace(/\n+$/, "");
  if (!/,\s*$/.test(text)) text += ",";
  mapOut += `${text}\n`;
}
// suffix already starts with `} as const;...`
mapOut += suffix.startsWith("}") ? suffix : `} as const;\n`;

// Local helpers in preamble may reference imports; include their bodies in scan.
const preambleWithoutImports = preamble.replace(/^import\s[\s\S]*?;\r?\n/gm, "");

function pruneImports(src, body) {
  return src.replace(
    /^import\s+\{([^}]+)\}\s+from\s+("[^"]+");\r?\n/gm,
    (full, names, from) => {
      const parts = names
        .split(",")
        .map((s) => s.trim())
        .filter(Boolean);
      const reallyKept = parts.filter((p) => {
        const id = p.split(/\s+as\s+/)[0].trim();
        return body.includes(id);
      });
      if (!reallyKept.length) return "";
      if (reallyKept.length === parts.length) return full;
      return `import {\n${reallyKept.map((n) => `  ${n},`).join("\n")}\n} from ${from};\n`;
    },
  );
}

let newPreamble = pruneImports(preamble, mapOut + preambleWithoutImports);
newPreamble = newPreamble.replace(/\n{3,}/g, "\n\n");
if (!newPreamble.endsWith("\n\n") && !newPreamble.endsWith("\n")) newPreamble += "\n";

const header = `// Wave 8 prune: removed ${removed.length} unused keys (${name} panel-componentization residue).\n`;
// Avoid stacking headers on re-run
const basePreamble = newPreamble.replace(/^(?:\/\/ Wave 8 prune:[^\n]*\n)+/, "");
const out = header + basePreamble + mapOut;

const summary = {
  name,
  total: allKeys.length,
  blocks: blocks.length,
  dead: removed.length,
  kept: keptBlocks.length,
  dynamicKept: [...dynamicStyleArgs].filter((k) => allKeys.includes(k) && !used.has(k)).length,
  removedSample: removed.slice(0, 20),
  dryRun,
};
console.log(JSON.stringify(summary, null, 2));

if (dryRun) process.exit(0);
writeFileSync(stylesPath, out);
console.log(`wrote ${stylesPath}`);
