// Lists style-map keys with no remaining call sites in the route or its tests.
// Usage: node scripts/find-dead-style-keys.mjs <RouteName>
import { readFileSync, existsSync } from "node:fs";

const name = process.argv[2] || "TeamsRoute";
const src = readFileSync(`src/routes/${name}.styles.ts`, "utf8");
const route = readFileSync(`src/routes/${name}.tsx`, "utf8");
const testPath = `src/routes/${name}.layout.test.ts`;
const test = existsSync(testPath) ? readFileSync(testPath, "utf8") : "";

const keys = [...src.matchAll(/^  ([A-Za-z0-9_]+):$/gm)].map((m) => m[1]);
// dynamic template lookups: styles[`prefix_${...}`] keep every key with that prefix
const dynPrefixes = [...route.matchAll(/styles\[`([A-Za-z0-9_]+?)\$\{/g)].map((m) => m[1]);

const dead = keys.filter((k) => {
  if (new RegExp(`styles\\.${k}\\b`).test(route)) return false;
  if (new RegExp(`routeStyles\\.${k}\\b`).test(test)) return false;
  if (dynPrefixes.some((p) => k.startsWith(p))) return false;
  return true;
});

console.log(`${name}: ${keys.length} keys total, ${dead.length} dead`);
console.log(dead.join("\n"));
