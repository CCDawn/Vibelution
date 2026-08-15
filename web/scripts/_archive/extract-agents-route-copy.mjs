/**
 * C1 / M10: extract agentsRouteCopy + agentConfigPanes out of AgentsRoute shell.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const outPath = path.join(root, "web/src/routes/agents/agentsRouteCopy.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i])) return i;
  }
  return -1;
};

const panesStart = find((l) => l.startsWith("function agentConfigPanes("));
const routeExportStart = find((l) => l.startsWith("export function AgentsRoute("));

if (panesStart < 0 || routeExportStart < 0) {
  console.error({ panesStart, routeExportStart });
  process.exit(1);
}

const block = lines.slice(panesStart, routeExportStart).map((line) => {
  if (line.startsWith("function agentsRouteCopy(") || line.startsWith("function agentConfigPanes(")) {
    return `export ${line}`;
  }
  return line;
}).join("\n");

const content = `/**
 * Agents workbench bilingual copy + pane badge helpers (structure C1).
 * Pure: no React hooks / Query / DOM.
 *
 * Ownership:
 * - Large Agents *workbench* copy stays here so AgentsRoute remains orchestration-only.
 * - Shared nav/compression keys remain in \`i18n/domains/dictionaryAgents.ts\` (D1 domain pack).
 * - Full merge into TranslationKey / useAppI18n is deferred until a dedicated dictionary charter.
 */
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import type { AgentConfigPaneId } from "./agentRouteManagementModel";

${block}
`;

fs.writeFileSync(outPath, content.replace(/export export /g, "export ").replace(/\n{3,}/g, "\n\n") + "\n");

const next = [...lines.slice(0, panesStart), ...lines.slice(routeExportStart)];
let route = next.join("\n");

const imp = `import {
  agentConfigPanes,
  agentsRouteCopy,
} from "./agents/agentsRouteCopy";
`;

if (!route.includes("agentsRouteCopy")) {
  route = route.replace(
    'from "./agents/agentRouteBulkModel";',
    `from "./agents/agentRouteBulkModel";\n${imp}`,
  );
}

fs.writeFileSync(routePath, route.replace(/\n{3,}/g, "\n\n") + "\n");
console.log("wrote", outPath);
console.log("copy lines", routeExportStart - panesStart);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("local agentsRouteCopy left", /function agentsRouteCopy\(/.test(route));
console.log("has import", route.includes("from \"./agents/agentsRouteCopy\""));
