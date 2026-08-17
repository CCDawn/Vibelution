import fs from "node:fs";
import path from "node:path";

const stylesPath = "web/src/routes/MemoryRoute.styles.ts";
const styles = fs.readFileSync(stylesPath, "utf8");
const keys = [...styles.matchAll(/^\s{2}([a-zA-Z][a-zA-Z0-9_]*):/gm)].map((m) => m[1]);

function walk(dir, out = []) {
  for (const name of fs.readdirSync(dir)) {
    const p = path.join(dir, name);
    const st = fs.statSync(p);
    if (st.isDirectory()) walk(p, out);
    else if (/\.(ts|tsx)$/.test(name) && !p.endsWith("MemoryRoute.styles.ts")) out.push(p);
  }
  return out;
}

const files = walk("web/src").map((f) => ({ f, t: fs.readFileSync(f, "utf8") }));
const importers = files.filter(({ t }) => t.includes("MemoryRoute.styles"));
console.log(
  "importers",
  importers.map((x) => x.f),
);

const live = {};
const dead = [];
for (const k of keys) {
  const needle = `styles.${k}`;
  const hits = importers.filter(({ t }) => t.includes(needle)).map((x) => x.f);
  if (hits.length) live[k] = hits;
  else dead.push(k);
}

const onlyRoute = [];
const onlyTest = [];
const both = [];
for (const [k, hits] of Object.entries(live)) {
  const prod = hits.filter((h) => !h.includes(".test."));
  const test = hits.filter((h) => h.includes(".test."));
  if (prod.length && !test.length) onlyRoute.push(k);
  else if (!prod.length && test.length) onlyTest.push(k);
  else both.push(k);
}

const summary = {
  total: keys.length,
  live: Object.keys(live).length,
  dead: dead.length,
  onlyRoute: onlyRoute.length,
  onlyTest: onlyTest.length,
  both: both.length,
};
console.log(summary);
console.log("onlyRoute", onlyRoute.join(","));
console.log("onlyTest count", onlyTest.length);
console.log("dead count", dead.length);

fs.writeFileSync(
  ".tmp-memory-style-audit.json",
  JSON.stringify({ summary, dead, onlyRoute, onlyTest, both, live }, null, 2),
);
