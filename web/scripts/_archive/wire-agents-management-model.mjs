import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
let lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const cut = (startPred, endPred) => {
  const start = lines.findIndex((l) => startPred(l));
  const end = lines.findIndex((l, i) => i > start && endPred(l));
  if (start < 0 || end < 0) {
    throw new Error(`cut failed ${start} ${end}`);
  }
  lines = [...lines.slice(0, start), ...lines.slice(end)];
};

// Remove higher line ranges first.
cut(
  (l) => l.startsWith("function groupDisplayLabel("),
  (l) => l.startsWith("function buildAgentCapabilityPreview("),
);
cut(
  (l) => l.startsWith("function buildVisibleAgentColumns("),
  (l) => l.startsWith("function safeAgentCenterReturnTo("),
);

let route = lines.join("\n");

const imp = `import {
  agentHasRuntimeSignal,
  buildAgentManagementBrief,
  buildManagementFilterGroups,
  buildVisibleAgentColumns,
  groupAriaLabel,
  groupDescription,
  groupDisplayLabel,
  groupSectionId,
  hasActionableHealthIssue,
  managementFilterMatches,
  normalizeAgentConfigPane,
  type AgentConfigPaneId,
  type AgentFilterGroup,
  type AgentManagementAction,
  type AgentManagementBrief,
  type AgentManagementFilterGroup,
} from "./agents/agentRouteManagementModel";
`;

if (!route.includes("agentRouteManagementModel")) {
  route = route.replace(
    'from "./agents/agentRouteDraftModel";',
    `from "./agents/agentRouteDraftModel";\n${imp}`,
  );
}

route = route.replace(/type AgentConfigPaneId = [^\n]+;\n/, "");
route = route.replace(/type AgentManagementAction = \{[\s\S]*?\n\};\n/, "");
route = route.replace(/type AgentManagementBrief = \{[\s\S]*?\n\};\n/, "");
route = route.replace(/type AgentManagementFilterGroup = \{[\s\S]*?\n\};\n/, "");
route = route.replace(/type AgentFilterGroup = [^\n]+;\n/, "");

fs.writeFileSync(routePath, route);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("has management import", route.includes("agentRouteManagementModel"));
console.log("has buildAgentManagementBrief fn", /function buildAgentManagementBrief\(/.test(route));
