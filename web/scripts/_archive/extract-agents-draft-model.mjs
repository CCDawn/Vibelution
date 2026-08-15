/**
 * M1 structure: extract Agents draft/mapper pure helpers.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const outPath = path.join(root, "web/src/routes/agents/agentRouteDraftModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) if (pred(lines[i])) return i;
  return -1;
};

const defaultCompressionStart = find((l) => l.startsWith("const DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT"));
const defaultCompressionEnd = find((l, i) => i > defaultCompressionStart && l.startsWith("const DEFAULT_BULK_CONFIG_DRAFT"), defaultCompressionStart);
// Fix find signature
const defaultCompressionEnd2 = find((l) => l.startsWith("const DEFAULT_BULK_CONFIG_DRAFT"), defaultCompressionStart);
const numericStart = find((l) => l.startsWith("function numericText("));
const afterDraft = find((l) => l.startsWith("function agentHasRuntimeSignal("));
const sortedStart = find((l) => l.startsWith("function sortedIds("));
const sortedEnd = find((l) => l.startsWith("function defaultToolPolicy("), sortedStart);

if ([defaultCompressionStart, defaultCompressionEnd2, numericStart, afterDraft, sortedStart, sortedEnd].some((i) => i < 0)) {
  console.error({ defaultCompressionStart, defaultCompressionEnd2, numericStart, afterDraft, sortedStart, sortedEnd });
  process.exit(1);
}

function exportFns(block) {
  return block.map((line) => {
    if (line.startsWith("function ")) return `export ${line}`;
    if (line.startsWith("const DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT")) {
      return line.replace(/^const /, "export const ");
    }
    return line;
  }).join("\n");
}

const defaults = exportFns(lines.slice(defaultCompressionStart, defaultCompressionEnd2));
const draftBlock = exportFns(lines.slice(numericStart, afterDraft));
const sortedBlock = exportFns(lines.slice(sortedStart, sortedEnd));

const content = `/**
 * Agents config/persona/task draft mappers (structure M1).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  AgentConfigWorkspaceAgent,
  AgentContextCompressionPolicy,
  AgentPersonaProfile,
  AgentTaskProfile,
  ToolPolicy,
} from "../../api/types";
import type { AgentContextCompressionPolicyDraft } from "../AgentContextCompressionPanel";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import type { AgentPersonaDraft } from "../AgentPersonaProfilePanel";
import type { AgentTaskDraft } from "../AgentTaskProfilePanel";
import {
  agentReasoningEffortBySlot,
  normalizeAgentLlmBindings,
  normalizeAgentReasoningEffortBySlot,
  sameAgentLlmBindings,
  sameAgentReasoningEffortBySlot,
} from "./agentRouteLlmModel";

export type AgentToolPolicyDraft = {
  allowedTools: string[];
  preferredTools: string[];
  blockedTools: string[];
  readScopes: string[];
  writeScopes: string[];
};

${defaults}

${sortedBlock}

${draftBlock}
`;

fs.writeFileSync(outPath, content.replace(/export export /g, "export "));

// Rebuild AgentsRoute without extracted blocks
const head = lines.slice(0, defaultCompressionStart);
const mid = lines.slice(defaultCompressionEnd2, numericStart); // DEFAULT_BULK through groupAriaLabel end, before numericText
const afterRuntime = lines.slice(afterDraft, sortedStart); // agentHasRuntimeSignal ... membershipDraftEquals
const tail = lines.slice(sortedEnd); // defaultToolPolicy onwards

let route = [...head, ...mid, ...afterRuntime, ...tail].join("\n");

const importBlock = `import {
  agentBoundaryType,
  agentHasTeamReference,
  configChangeSnapshotFromDraft,
  contextCompressionDraftEqualsDraft,
  contextCompressionDraftFromAgent,
  contextCompressionPolicyFromDraft,
  DEFAULT_AGENT_CONTEXT_COMPRESSION_DRAFT,
  draftEqualsAgent,
  draftFromAgent,
  expertiseFromDraft,
  hasModelAndPromptConfiguration,
  hasPersonaProfile,
  hasTaskProfile,
  hasToolPolicyConfiguration,
  hasWorkspaceConfiguration,
  isWorkSessionAgent,
  normalizePersonaProfile,
  normalizeTaskProfile,
  normalizeToolPolicyDraftForAgent,
  personaDraftEqualsAgent,
  personaDraftFromAgent,
  personaProfileFromDraft,
  personaProfileSummary,
  requiresPersonaProfile,
  requiresTaskProfile,
  requiresTeamMembership,
  sameStringSet,
  sortedIds,
  taskDraftEqualsAgent,
  taskDraftFromAgent,
  taskProfileFromDraft,
  taskProfileSummary,
} from "./agents/agentRouteDraftModel";
`;

if (!route.includes("agentRouteDraftModel")) {
  route = route.replace(
    'from "./agents/agentRouteWorkspaceModel";',
    `from "./agents/agentRouteWorkspaceModel";\n${importBlock}`,
  );
}

// Remove local type AgentToolPolicyDraft if still defined in route and re-export from draft model via import type
// Keep route type if layout tests need it - draft model has its own; route still has type AgentToolPolicyDraft

fs.writeFileSync(routePath, route);
console.log("wrote", outPath);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("extracted draft helpers", afterDraft - numericStart, "sorted", sortedEnd - sortedStart);
