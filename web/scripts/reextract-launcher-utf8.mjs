/**
 * Re-extract TeamResearchStageLauncherPanel from 1bcefd64a TeamsRoute (good UTF-8),
 * then re-apply standalone extract on current TeamsRoute.
 */
import { execSync } from "node:child_process";
import { readFileSync, writeFileSync } from "node:fs";

const hash = execSync("git rev-parse 1bcefd64a:web/src/routes/TeamsRoute.tsx", { encoding: "utf8" }).trim();
const blob = execSync(`git cat-file -p ${hash}`);
const src = blob.toString("utf8");
console.log("source 证据链", src.includes("证据链"), "科研控制台", src.includes("科研控制台"));

const start = src.indexOf("  function renderResearchStageLauncher() {");
const end = src.indexOf("  function renderResearchCanvasReadOnlyPanel() {");
if (start < 0 || end <= start) {
  console.error("markers", start, end);
  process.exit(1);
}
const fn = src.slice(start, end);
const bodyStart = fn.indexOf("{");
const body = fn.slice(bodyStart);
const statements = body.slice(1, body.lastIndexOf("}"));

// Read current header/props from existing (broken) panel file structure - rebuild header cleanly
const header = readFileSync("src/routes/TeamResearchStageLauncherPanel.tsx", "utf8");
// Keep everything up through `= props;`
const propsEnd = header.indexOf("  } = props;");
if (propsEnd < 0) {
  console.error("props destructure not found in current panel");
  process.exit(1);
}
const head = header.slice(0, propsEnd + "  } = props;".length);

const fixed = `${head}\n\n${statements}\n}\n`;
writeFileSync("src/routes/TeamResearchStageLauncherPanel.tsx", fixed);
console.log("rewrote launcher panel", fixed.length, "证据链", fixed.includes("证据链"), "科研控制台", fixed.includes("科研控制台"));
