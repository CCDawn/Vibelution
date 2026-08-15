/**
 * Wave 8A: keep only MemoryRoute.tsx-referenced keys in MemoryRoute.styles.ts.
 */
import fs from "node:fs";

const stylesPath = "web/src/routes/MemoryRoute.styles.ts";
const routePath = "web/src/routes/MemoryRoute.tsx";
const stylesSrc = fs.readFileSync(stylesPath, "utf8");
const routeSrc = fs.readFileSync(routePath, "utf8");

const used = [
  ...new Set([...routeSrc.matchAll(/styles\.([a-zA-Z0-9_]+)/g)].map((m) => m[1])),
].sort();

const mapStart = stylesSrc.indexOf("const styles = {");
const mapEnd = stylesSrc.lastIndexOf("} as const;");
if (mapStart < 0 || mapEnd < 0) {
  throw new Error("Could not locate styles map");
}
const preamble = stylesSrc.slice(0, mapStart);
const mapBody = stylesSrc.slice(mapStart + "const styles = {".length, mapEnd);

// Split body into key blocks by scanning for lines that start a new key at indent 2.
const lines = mapBody.split("\n");
const blocks = [];
let current = null;
for (const line of lines) {
  const keyMatch = line.match(/^  ([a-zA-Z][a-zA-Z0-9_]*)\s*:/);
  const commentOnly = line.match(/^  \/\/(.*)$/);
  if (keyMatch) {
    if (current) blocks.push(current);
    current = { key: keyMatch[1], lines: [line], leadingComments: [] };
  } else if (current) {
    current.lines.push(line);
  } else if (commentOnly) {
    // orphan comment before first key — ignore
  }
}
if (current) blocks.push(current);

const byKey = new Map(blocks.map((b) => [b.key, b]));
const missing = used.filter((k) => !byKey.has(k));
if (missing.length) {
  console.error("Missing style definitions:", missing);
  process.exit(1);
}

const keptBlocks = used.map((k) => byKey.get(k));
const keptText = keptBlocks.map((b) => b.lines.join("\n")).join("\n");

// Rebuild imports based on used tokens in kept text
const tokens = {
  vuiControlPillClass: keptText.includes("vuiControlPillClass"),
  vuiStateSelectedRowClass: keptText.includes("vuiStateSelectedRowClass"),
  vuiWorkspaceFillClass: keptText.includes("vuiWorkspaceFillClass"),
  vuiOpaqueRowClass: keptText.includes("vuiOpaqueRowClass"),
  vuiFlatPanelClass: keptText.includes("vuiFlatPanelClass"),
  vuiStateCoolSoftClass: keptText.includes("vuiStateCoolSoftClass"),
  vuiStateCoolInfoClass: keptText.includes("vuiStateCoolInfoClass"),
};

const chrome = [];
if (tokens.vuiControlPillClass) chrome.push("  vuiControlPillClass,");
const surface = [];
for (const name of [
  "vuiFlatPanelClass",
  "vuiOpaqueRowClass",
  "vuiStateCoolInfoClass",
  "vuiStateCoolSoftClass",
  "vuiStateSelectedRowClass",
  "vuiWorkspaceFillClass",
]) {
  if (tokens[name]) surface.push(`  ${name},`);
}

let out = `// Memory route shell styles (Wave 8A prune).
// Panel-owned classes live under *Panel.styles.ts after domain componentization.
// Keep only keys referenced by MemoryRoute.tsx.
`;
if (chrome.length) {
  out += `\nimport {\n${chrome.join("\n")}\n} from "../design/vuiChromeRecipes";\n`;
}
if (surface.length) {
  out += `\nimport {\n${surface.join("\n")}\n} from "../design/vuiSurfaceRecipes";\n`;
}
out += `\nconst styles = {\n`;
for (const block of keptBlocks) {
  // Ensure block ends with comma
  let text = block.lines.join("\n");
  // Drop trailing blank lines inside block
  text = text.replace(/\n+$/, "");
  if (!/,\s*$/.test(text)) text += ",";
  out += `${text}\n`;
}
out += `} as const;\n\nexport default styles;\n`;

fs.writeFileSync(stylesPath, out);
console.log(
  JSON.stringify(
    {
      before: blocks.length,
      after: used.length,
      removed: blocks.length - used.length,
      used,
    },
    null,
    2,
  ),
);
