/**
 * Wave 8F: split TeamsRoute.styles into thematic cluster maps while keeping
 * a merged `styles` object in TeamsRoute.tsx (no call-site rewrites).
 *
 * Usage (from web/): node scripts/extract-teams-style-clusters.mjs [--dry-run]
 */
import { readFileSync, writeFileSync } from "node:fs";

const dryRun = process.argv.includes("--dry-run");
const stylesPath = "src/routes/TeamsRoute.styles.ts";
const routePath = "src/routes/TeamsRoute.tsx";
const stylesSrc = readFileSync(stylesPath, "utf8");

const CLUSTERS = [
  {
    id: "research",
    out: "src/routes/TeamsRoute.research.styles.ts",
    importName: "researchRouteStyles",
    importPath: "./TeamsRoute.research.styles",
    match: (k) =>
      k.startsWith("research")
      || k.startsWith("challengeWorkspace")
      || k.startsWith("challengeCup")
      || k.startsWith("knowledgeCompletion"),
  },
  {
    id: "aiSearch",
    out: "src/routes/TeamsRoute.aiSearch.styles.ts",
    importName: "aiSearchRouteStyles",
    importPath: "./TeamsRoute.aiSearch.styles",
    match: (k) => k.startsWith("aiSearch") || k.startsWith("scopeChip") || k.startsWith("searchScope"),
  },
  {
    id: "experiment",
    out: "src/routes/TeamsRoute.experiment.styles.ts",
    importName: "experimentRouteStyles",
    importPath: "./TeamsRoute.experiment.styles",
    match: (k) => k.startsWith("experiment"),
  },
  {
    id: "workflow",
    out: "src/routes/TeamsRoute.workflow.styles.ts",
    importName: "workflowRouteStyles",
    importPath: "./TeamsRoute.workflow.styles",
    match: (k) =>
      k.startsWith("workflow")
      || k.startsWith("teamRound")
      || k.startsWith("teamHistory")
      || k.startsWith("teamBus")
      || k.startsWith("kernelTrace")
      || k.startsWith("linkedRoom"),
  },
];

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
  return {
    preamble: src.slice(0, mapDecl.index),
    mapDecl: mapDecl[0],
    suffix: src.slice(mapEnd),
    blocks,
  };
}

const CHROME = ["vuiControlPillClass", "vuiControlQuietClass"];
const SURFACE = [
  "vuiDenseRowClass",
  "vuiElevatedPanelClass",
  "vuiFlatPanelClass",
  "vuiGlassPanelClass",
  "vuiOpaqueRowClass",
  "vuiRailFillClass",
  "vuiStateAccentBannerClass",
  "vuiStateCoolInfoClass",
  "vuiStateCoolSoftClass",
  "vuiStateDangerSoftClass",
  "vuiStateSelectedRowClass",
  "vuiStateSelectedRowFillClass",
  "vuiStateSelectedWarmRowClass",
  "vuiStateSuccessSoftClass",
  "vuiStateWarmSoftClass",
  "vuiStateWarningSoftClass",
  "vuiWorkspaceFillClass",
  "vuiChatFillClass",
  "vuiToolbarFillClass",
];

function buildMapFile(blocks, comment) {
  const body = blocks
    .map((b) => {
      let t = b.lines.join("\n").replace(/\n+$/, "");
      if (!/,\s*$/.test(t)) t += ",";
      return t;
    })
    .join("\n");
  const chrome = CHROME.filter((n) => body.includes(n));
  const surface = SURFACE.filter((n) => body.includes(n));
  // Detect local const helpers used in kept blocks - leave them in shell only.
  let out = `// ${comment}\n`;
  if (chrome.length) {
    out += `\nimport {\n${chrome.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiChromeRecipes";\n`;
  }
  if (surface.length) {
    out += `\nimport {\n${surface.map((n) => `  ${n},`).join("\n")}\n} from "../design/vuiSurfaceRecipes";\n`;
  }
  out += `\nconst styles = {\n${body}\n} as const;\n\nexport default styles;\n`;
  return out;
}

const parsed = parseBlocks(stylesSrc);
const assigned = new Map(); // key -> cluster id
const clusterBlocks = Object.fromEntries(CLUSTERS.map((c) => [c.id, []]));

for (const block of parsed.blocks) {
  const cluster = CLUSTERS.find((c) => c.match(block.key));
  if (cluster) {
    clusterBlocks[cluster.id].push(block);
    assigned.set(block.key, cluster.id);
  }
}

const shellBlocks = parsed.blocks.filter((b) => !assigned.has(b.key));

const report = {
  dryRun,
  total: parsed.blocks.length,
  shell: shellBlocks.length,
  clusters: Object.fromEntries(
    CLUSTERS.map((c) => [c.id, clusterBlocks[c.id].length]),
  ),
};
console.log(JSON.stringify(report, null, 2));
if (dryRun) process.exit(0);

// Write cluster files
for (const c of CLUSTERS) {
  const blocks = clusterBlocks[c.id];
  if (!blocks.length) continue;
  writeFileSync(
    c.out,
    buildMapFile(blocks, `Wave 8F: ${c.id} cluster extracted from TeamsRoute.styles`),
  );
  console.log(`wrote ${c.out} (${blocks.length} keys)`);
}

// Rebuild shell styles - preserve local const helpers from original preamble
// Original may have local const helpers between imports and map.
const originalPreamble = parsed.preamble;
// Drop old header comments that mention full map only; keep imports + local consts
const shellBody = shellBlocks
  .map((b) => {
    let t = b.lines.join("\n").replace(/\n+$/, "");
    if (!/,\s*$/.test(t)) t += ",";
    return t;
  })
  .join("\n");

// Rebuild imports for shell based on shellBody + local const section
const localSection = originalPreamble
  .replace(/^[\s\S]*?(?=^(?:import |const |function |\/\/))/m, "")
  .replace(/^import[\s\S]*?;\r?\n/gm, "");

// Keep original imports but prune unused recipe names against shellBody + localSection
function pruneImports(preamble, body) {
  return preamble.replace(
    /^import\s+\{([^}]+)\}\s+from\s+("[^"]+");\r?\n/gm,
    (full, names, from) => {
      if (!from.includes("vuiChromeRecipes") && !from.includes("vuiSurfaceRecipes")) {
        // keep non-recipe imports if referenced
        const parts = names.split(",").map((s) => s.trim()).filter(Boolean);
        const kept = parts.filter((p) => {
          const id = p.split(/\s+as\s+/)[0].trim();
          return body.includes(id);
        });
        if (!kept.length) return "";
        if (kept.length === parts.length) return full;
        return `import {\n${kept.map((n) => `  ${n},`).join("\n")}\n} from ${from};\n`;
      }
      const parts = names.split(",").map((s) => s.trim()).filter(Boolean);
      const kept = parts.filter((p) => {
        const id = p.split(/\s+as\s+/)[0].trim();
        return body.includes(id);
      });
      if (!kept.length) return "";
      if (kept.length === parts.length) return full;
      return `import {\n${kept.map((n) => `  ${n},`).join("\n")}\n} from ${from};\n`;
    },
  );
}

const scanBody = shellBody + "\n" + localSection;
let shellPreamble = pruneImports(originalPreamble, scanBody);
// Ensure Wave 8F header
shellPreamble = shellPreamble.replace(/^(?:\/\/ Wave 8[^\n]*\n)+/, "");
const shellOut =
  `// TeamsRoute shell styles (Wave 8F cluster split).
// Thematic maps: research / aiSearch / experiment / workflow.
// TeamsRoute.tsx merges clusters into a single styles object.
` + shellPreamble + `${parsed.mapDecl.includes("Record") ? parsed.mapDecl : "const styles = {"}\n${shellBody}\n` +
  (parsed.suffix.startsWith("}") || parsed.suffix.startsWith("\n}")
    ? parsed.suffix
    : "} as const;\n\nexport default styles;\n");

// Fix double const styles if mapDecl already has it
const shellFixed = shellOut.replace(
  /const styles = \{\nconst styles = \{/,
  "const styles = {",
).replace(
  /const styles: Record<string, string> = \{\nconst styles = \{/,
  "const styles: Record<string, string> = {",
);

writeFileSync(stylesPath, shellFixed);
console.log(`wrote ${stylesPath} shell (${shellBlocks.length} keys)`);

// Patch TeamsRoute.tsx imports
let route = readFileSync(routePath, "utf8");
if (!route.includes("TeamsRoute.research.styles")) {
  route = route.replace(
    /import styles from "\.\/TeamsRoute\.styles";/,
    `import shellStyles from "./TeamsRoute.styles";
import researchRouteStyles from "./TeamsRoute.research.styles";
import aiSearchRouteStyles from "./TeamsRoute.aiSearch.styles";
import experimentRouteStyles from "./TeamsRoute.experiment.styles";
import workflowRouteStyles from "./TeamsRoute.workflow.styles";

/** Wave 8F: thematic style clusters merged for call-site stability. */
const styles = {
  ...shellStyles,
  ...researchRouteStyles,
  ...aiSearchRouteStyles,
  ...experimentRouteStyles,
  ...workflowRouteStyles,
} as Record<string, string>;`,
  );
  writeFileSync(routePath, route);
  console.log("patched TeamsRoute.tsx style merge");
} else {
  console.log("TeamsRoute.tsx already merged");
}

// Patch layout test routeStylesBase merge if needed
const layoutPath = "src/routes/TeamsRoute.layout.test.ts";
let layout = readFileSync(layoutPath, "utf8");
if (!layout.includes("TeamsRoute.research.styles")) {
  layout = layout.replace(
    /import routeStylesBase from "\.\/TeamsRoute\.styles";/,
    `import shellRouteStyles from "./TeamsRoute.styles";
import researchRouteStyles from "./TeamsRoute.research.styles";
import aiSearchRouteStyles from "./TeamsRoute.aiSearch.styles";
import experimentRouteStyles from "./TeamsRoute.experiment.styles";
import workflowRouteStyles from "./TeamsRoute.workflow.styles";
const routeStylesBase = {
  ...shellRouteStyles,
  ...researchRouteStyles,
  ...aiSearchRouteStyles,
  ...experimentRouteStyles,
  ...workflowRouteStyles,
} as Record<string, string>;`,
  );
  // routeStylesModuleSource still from shell - expand for scans
  if (layout.includes("routeStylesModuleSource from")) {
    layout = layout.replace(
      /import routeStylesModuleSource from "\.\/TeamsRoute\.styles\.ts\?raw";/,
      `import shellRouteStylesModuleSource from "./TeamsRoute.styles.ts?raw";
import researchRouteStylesModuleSource from "./TeamsRoute.research.styles.ts?raw";
import aiSearchRouteStylesModuleSource from "./TeamsRoute.aiSearch.styles.ts?raw";
import experimentRouteStylesModuleSource from "./TeamsRoute.experiment.styles.ts?raw";
import workflowRouteStylesModuleSource from "./TeamsRoute.workflow.styles.ts?raw";
const routeStylesModuleSource = [
  shellRouteStylesModuleSource,
  researchRouteStylesModuleSource,
  aiSearchRouteStylesModuleSource,
  experimentRouteStylesModuleSource,
  workflowRouteStylesModuleSource,
].join("\\n");`,
    );
  }
  writeFileSync(layoutPath, layout);
  console.log("patched TeamsRoute.layout.test.ts style merge");
}

console.log("done");
