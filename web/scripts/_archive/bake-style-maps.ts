/**
 * Phase 0 "explicit style baseline" bake (2026-07-02 spec).
 *
 * Evaluates each createVuiStyleMap-based style module at runtime and rewrites
 * it as a plain explicit key → Tailwind-class map, byte-identical per key.
 * This removes the key-name magic inference (the lossy-migration bug class)
 * with zero visual change.
 *
 * Usage (run from web/):
 *   node_modules/.bin/vite-node scripts/bake-style-maps.ts dump    # snapshot current resolved maps → scripts/.style-map-snapshot.json
 *   node_modules/.bin/vite-node scripts/bake-style-maps.ts bake [Name ...]   # rewrite target files (optionally only the named modules)
 *   node_modules/.bin/vite-node scripts/bake-style-maps.ts verify  # re-import and diff against the snapshot
 */
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

import appShellStyles from "../src/app/AppShell.styles";
import conversationViewStyles from "../src/components/conversation/ConversationView.styles";
import agentsRouteStyles from "../src/routes/AgentsRoute.styles";
import chatCodingRouteStyles from "../src/routes/ChatCodingRoute.styles";
import evolutionRouteStyles from "../src/routes/EvolutionRoute.styles";
import logsRouteStyles from "../src/routes/LogsRoute.styles";
import memoryRouteStyles from "../src/routes/MemoryRoute.styles";
import researchFlowCanvasRouteStyles from "../src/routes/ResearchFlowCanvasRoute.styles";
import researchRouteStyles from "../src/routes/ResearchRoute.styles";
import teamsRouteStyles from "../src/routes/TeamsRoute.styles";
import toolsRouteStyles from "../src/routes/ToolsRoute.styles";

const here = path.dirname(fileURLToPath(import.meta.url));
const SNAPSHOT = path.join(here, ".style-map-snapshot.json");

/** Target name → [resolved module default export, file to rewrite]. */
const TARGETS: Record<string, [Record<string, string>, string]> = {
  AppShell: [appShellStyles, "../src/app/AppShell.styles.ts"],
  ConversationView: [conversationViewStyles, "../src/components/conversation/ConversationView.styles.ts"],
  AgentsRoute: [agentsRouteStyles, "../src/routes/AgentsRoute.styles.ts"],
  ChatCodingRoute: [chatCodingRouteStyles, "../src/routes/ChatCodingRoute.styles.ts"],
  EvolutionRoute: [evolutionRouteStyles, "../src/routes/EvolutionRoute.styles.ts"],
  LogsRoute: [logsRouteStyles, "../src/routes/LogsRoute.styles.ts"],
  MemoryRoute: [memoryRouteStyles, "../src/routes/MemoryRoute.styles.ts"],
  ResearchFlowCanvasRoute: [researchFlowCanvasRouteStyles, "../src/routes/ResearchFlowCanvasRoute.styles.ts"],
  ResearchRoute: [researchRouteStyles, "../src/routes/ResearchRoute.styles.ts"],
  TeamsRoute: [teamsRouteStyles, "../src/routes/TeamsRoute.styles.ts"],
  ToolsRoute: [toolsRouteStyles, "../src/routes/ToolsRoute.styles.ts"],
};

type Snapshot = Record<string, Record<string, string>>;

/**
 * The pre-bake maps are Proxies: ANY key access — including keys never listed
 * in styleKeys ("phantom keys" used directly by consumers) and dynamic
 * `styles[\`prefix_${tone}\`]` lookups — synthesizes classes by name inference.
 * A spread only captures declared keys, so the dump must also:
 *   1. statically scan every consumer (including tests) for `alias.key` accesses;
 *   2. cover dynamic template lookups by crossing each `prefix_` with the
 *      project's suffix vocabulary (suffixes of declared keys + tone words).
 * Extra keys cost a few strings; missing keys silently drop styling.
 */
const TONE_VOCAB = [
  "active", "blocked", "danger", "done", "error", "failed", "idle", "info",
  "mental", "missing", "muted", "neutral", "ok", "pending", "ready", "running",
  "status", "success", "thought", "warn", "warning",
];

function walk(dir: string, acc: string[] = []): string[] {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, entry.name);
    if (entry.isDirectory()) walk(p, acc);
    else if (/\.(ts|tsx)$/.test(entry.name) && !entry.name.endsWith(".styles.ts")) acc.push(p);
  }
  return acc;
}

/** target name → module basename used in import specifiers. */
function importBasename(name: string): string {
  return `${name}.styles`;
}

function collectAccessedKeys(): Record<string, { statics: Set<string>; prefixes: Set<string> }> {
  const acc: Record<string, { statics: Set<string>; prefixes: Set<string> }> = {};
  for (const name of Object.keys(TARGETS)) acc[name] = { statics: new Set(), prefixes: new Set() };
  const files = walk(path.join(here, "../src"));
  for (const file of files) {
    const src = readFileSync(file, "utf8");
    for (const name of Object.keys(TARGETS)) {
      const importRe = new RegExp(`import\\s+(\\w+)\\s+from\\s+"[^"]*${importBasename(name)}"`);
      const m = importRe.exec(src);
      if (!m) continue;
      const alias = m[1];
      for (const sm of src.matchAll(new RegExp(`\\b${alias}\\.([A-Za-z_$][A-Za-z0-9_$]*)`, "g"))) {
        acc[name].statics.add(sm[1]);
      }
      for (const dm of src.matchAll(new RegExp(`\\b${alias}\\[\\\`([A-Za-z0-9_$]*?)\\$\\{`, "g"))) {
        if (dm[1]) acc[name].prefixes.add(dm[1]);
      }
    }
  }
  return acc;
}

function loadResolved(includePhantoms: boolean): Snapshot {
  const accessed = includePhantoms ? collectAccessedKeys() : null;
  const out: Snapshot = {};
  for (const [name, [styles]] of Object.entries(TARGETS)) {
    if (!styles || typeof styles !== "object") {
      throw new Error(`${name}: default export is not an object`);
    }
    const map: Record<string, string> = { ...styles };
    if (accessed) {
      const declaredSuffixes = Object.keys(map)
        .filter((k) => k.includes("_"))
        .map((k) => k.slice(k.indexOf("_") + 1));
      const vocab = new Set([...TONE_VOCAB, ...declaredSuffixes]);
      const wanted = new Set<string>(accessed[name].statics);
      for (const prefix of accessed[name].prefixes) {
        for (const suffix of vocab) wanted.add(`${prefix}${suffix}`);
      }
      for (const key of wanted) {
        if (!(key in map)) {
          const value = (styles as Record<string, string>)[key];
          if (typeof value === "string") map[key] = value;
        }
      }
    }
    out[name] = map;
  }
  return out;
}

const IDENT = /^[A-Za-z_$][A-Za-z0-9_$]*$/;

function generate(name: string, map: Record<string, string>): string {
  const lines: string[] = [];
  lines.push(
    "// Explicit style baseline (Phase 0, 2026-07-02 spec) — generated by",
    "// web/scripts/bake-style-maps.ts from the previous createVuiStyleMap output;",
    "// classes are byte-identical to what the inference produced. Every key is an",
    "// explicit Tailwind class string; there are no name-based defaults. Edit",
    "// values directly. This file is transitional: it is deleted in the wave that",
    `// componentizes ${name}.`,
    "// Includes phantom keys (accessed by consumers but never declared in the old",
    "// styleKeys — the Proxy synthesized them on demand) and prefix×tone-vocabulary",
    "// coverage for dynamic `styles[`prefix_${tone}`]` lookups. Typed loosely as",
    "// Record<string, string> because those dynamic template indexes cannot index a",
    "// literal-keyed map; tightening is a follow-up, not Phase 0.",
    "const styles: Record<string, string> = {",
  );
  for (const key of Object.keys(map).sort()) {
    const k = IDENT.test(key) ? key : JSON.stringify(key);
    lines.push(`  ${k}:`);
    lines.push(`    ${JSON.stringify(map[key])},`);
  }
  lines.push("};", "", "export default styles;", "");
  return lines.join("\n");
}

const [, , command, ...only] = process.argv;

if (command === "dump") {
  const snap = loadResolved(true);
  writeFileSync(SNAPSHOT, JSON.stringify(snap, null, 1));
  const counts = Object.entries(snap).map(([n, m]) => `${n}:${Object.keys(m).length}`);
  console.log(`snapshot written (${counts.join(", ")})`);
} else if (command === "bake") {
  const snap: Snapshot = JSON.parse(readFileSync(SNAPSHOT, "utf8"));
  const names = only.length ? only : Object.keys(TARGETS);
  for (const name of names) {
    if (!TARGETS[name]) throw new Error(`unknown target ${name}`);
    const file = path.join(here, TARGETS[name][1]);
    writeFileSync(file, generate(name, snap[name]));
    console.log(`baked ${name} (${Object.keys(snap[name]).length} keys)`);
  }
} else if (command === "verify") {
  const snap: Snapshot = JSON.parse(readFileSync(SNAPSHOT, "utf8"));
  const now = loadResolved(false);
  let bad = 0;
  for (const [name, expected] of Object.entries(snap)) {
    const actual = now[name] ?? {};
    const keys = new Set([...Object.keys(expected), ...Object.keys(actual)]);
    for (const key of keys) {
      if (expected[key] !== actual[key]) {
        bad += 1;
        console.log(`MISMATCH ${name}.${key}`);
        console.log(`  before: ${expected[key]}`);
        console.log(`  after:  ${actual[key]}`);
      }
    }
  }
  console.log(bad === 0 ? "VERIFY OK — all keys byte-identical" : `VERIFY FAILED — ${bad} mismatches`);
  if (bad) process.exit(1);
} else {
  console.log("usage: vite-node scripts/bake-style-maps.ts dump|bake [names]|verify");
  process.exit(2);
}
