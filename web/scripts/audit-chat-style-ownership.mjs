/**
 * Wave 8C: classify ChatCodingRoute.styles keys by production importer.
 * Usage (from web/): node scripts/audit-chat-style-ownership.mjs
 */
import { readFileSync, readdirSync, writeFileSync } from "node:fs";
import path from "node:path";

const name = "ChatCodingRoute";
const stylesPath = `src/routes/${name}.styles.ts`;
const stylesSrc = readFileSync(stylesPath, "utf8");
const keys = [...stylesSrc.matchAll(/^  ([A-Za-z0-9_]+):(?:$|\s)/gm)].map((m) => m[1]);

function walk(dir, acc = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name)) acc.push(p);
  }
  return acc;
}

const used = new Map(); // key -> Set of files
const dynPrefixes = new Set();
const importerFiles = [];

for (const file of walk("src")) {
  if (path.resolve(file) === path.resolve(stylesPath)) continue;
  const text = readFileSync(file, "utf8");
  const m = new RegExp(`import\\s+(\\w+)\\s+from\\s+"[^"]*${name}\\.styles"`).exec(text);
  if (!m) continue;
  importerFiles.push(file);
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

const allImp = importerFiles.map((f) => readFileSync(f, "utf8")).join("\n");
const dead = keys.filter((k) => {
  if (used.has(k)) return false;
  if ([...dynPrefixes].some((p) => k.startsWith(p))) return false;
  const us = k.indexOf("_");
  if (us > 0 && allImp.includes(`${k.slice(0, us)}_`)) return false;
  return true;
});

const byProdFile = {};
const onlyTest = [];
const multiProd = [];
const singleProd = {};

for (const k of keys) {
  if (dead.includes(k)) continue;
  const files = [...(used.get(k) || [])];
  const prod = files.filter((f) => !f.includes(".test."));
  const test = files.filter((f) => f.includes(".test."));
  if (!prod.length) {
    onlyTest.push(k);
    continue;
  }
  const uniq = [...new Set(prod)];
  if (uniq.length === 1) {
    const f = uniq[0];
    if (!singleProd[f]) singleProd[f] = [];
    singleProd[f].push(k);
  } else {
    multiProd.push({ k, files: uniq });
  }
  for (const f of uniq) {
    byProdFile[f] = (byProdFile[f] || 0) + 1;
  }
}

const summary = {
  total: keys.length,
  dead: dead.length,
  onlyTest: onlyTest.length,
  multiProd: multiProd.length,
  singleProdFiles: Object.fromEntries(
    Object.entries(singleProd)
      .map(([f, ks]) => [f, ks.length])
      .sort((a, b) => b[1] - a[1]),
  ),
  dynPrefixes: [...dynPrefixes],
  deadKeys: dead,
  onlyTestSample: onlyTest.slice(0, 40),
  topSingle: Object.entries(singleProd)
    .sort((a, b) => b[1].length - a[1].length)
    .slice(0, 12)
    .map(([f, ks]) => ({ file: f, count: ks.length, sample: ks.slice(0, 15) })),
};

console.log(JSON.stringify(summary, null, 2));
writeFileSync("../.tmp-chat-style-ownership.json", JSON.stringify({ ...summary, singleProd, multiProd }, null, 2));
console.log("wrote ../.tmp-chat-style-ownership.json");
