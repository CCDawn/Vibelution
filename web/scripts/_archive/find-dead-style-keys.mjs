// Lists style-map keys with no remaining call sites anywhere in src (all
// importers discovered automatically, each scanned under its own import alias;
// dynamic `alias[`prefix_${...}`]` lookups keep every key with that prefix).
// Usage: node scripts/find-dead-style-keys.mjs <RouteName> [--json]
import { readFileSync, readdirSync } from "node:fs";
import path from "node:path";

const name = process.argv[2] || "TeamsRoute";
const asJson = process.argv.includes("--json");

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

const stylesPath = `src/routes/${name}.styles.ts`;
const src = readFileSync(stylesPath, "utf8");
const keys = [...src.matchAll(/^  ([A-Za-z0-9_]+):$/gm)].map((m) => m[1]);

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
}
const allImporterText = importerTexts.join("\n");

const dead = keys.filter((k) => {
  if (used.has(k)) return false;
  if ([...dynPrefixes].some((p) => k.startsWith(p))) return false;
  // Computed-key protection: helper functions build keys as `prefix_${...}`
  // (e.g. agentRoleClass → `agentRoleTag_${tone}`). If a suffixed key's
  // `prefix_` fragment appears anywhere in importer source, keep it.
  const us = k.indexOf("_");
  if (us > 0 && allImporterText.includes(`${k.slice(0, us)}_`)) return false;
  return true;
});

if (asJson) {
  console.log(JSON.stringify(dead));
} else {
  console.log(`${name}: ${keys.length} keys total, ${dead.length} dead`);
  console.log(dead.join("\n"));
}
