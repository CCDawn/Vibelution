/**
 * D3: extract LLM + lightweight workspace pure helpers from AgentsRoute.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const llmPath = path.join(root, "web/src/routes/agents/agentRouteLlmModel.ts");
const workspacePath = path.join(root, "web/src/routes/agents/agentRouteWorkspaceModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

function findLine(pred, from = 0) {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i], i)) return i;
  }
  return -1;
}

const fallbackStart = findLine((l) => l.startsWith("const FALLBACK_AGENT_LLM_SLOTS"));
const fallbackEnd = findLine((l, i) => i > fallbackStart && l.startsWith("const EMPTY_TOOL_BUNDLES"));
const lightStart = findLine((l) => l.startsWith("const LIGHTWEIGHT_AGENT_CONFIG_STORAGE"));
const lightEnd = findLine((l, i) => i > lightStart && l.startsWith("const DEFAULT_AGENT_RESET_OPTIONS"));

const llmStart = findLine((l) => l.startsWith("function agentLlmSlots("));
const llmEnd = findLine((l, i) => i > llmStart && l.startsWith("function referenceLabel("));
const wsStart = findLine((l) => l.startsWith("function referenceLabel("));
const wsEnd = findLine((l, i) => i > wsStart && l.startsWith("function buildVisibleAgentColumns("));

if ([fallbackStart, fallbackEnd, lightStart, lightEnd, llmStart, llmEnd, wsStart, wsEnd].some((i) => i < 0)) {
  console.error({ fallbackStart, fallbackEnd, lightStart, lightEnd, llmStart, llmEnd, wsStart, wsEnd });
  process.exit(1);
}

function exportFunctions(blockLines) {
  return blockLines.map((line) => {
    if (line.startsWith("function ")) return line.replace(/^function /, "export function ");
    if (line.startsWith("const AGENT_REASONING_EFFORT_VALUES")) {
      return line.replace(/^const /, "export const ");
    }
    if (line.startsWith("const FALLBACK_AGENT_LLM_SLOTS")) {
      return line.replace(/^const /, "export const ");
    }
    if (line.startsWith("const LIGHTWEIGHT_AGENT_CONFIG_STORAGE")) {
      return line.replace(/^const /, "export const ");
    }
    return line;
  });
}

const fallbackBlock = exportFunctions(lines.slice(fallbackStart, fallbackEnd)).join("\n");
const lightBlock = exportFunctions(lines.slice(lightStart, lightEnd)).join("\n");
const llmBlock = exportFunctions(lines.slice(llmStart, llmEnd)).join("\n");
const wsBlock = exportFunctions(lines.slice(wsStart, wsEnd)).join("\n")
  // inject local hasActionable for lightweight group health counts
  .replace(
    "healthCount: agents.filter((agent) => agentIds.includes(agent.agentId) && hasActionableHealthIssue(agent)).length,",
    "healthCount: agents.filter((agent) => agentIds.includes(agent.agentId) && hasActionableHealthIssue(agent)).length,",
  )
  // filterAgents uses managementFilterMatches — inject optional callback
  .replace(
    `function filterAgents(
  workspace: AgentConfigWorkspace | undefined,
  activeFilter: FilterId,
  searchText: string,
) {
  const agents = workspace?.agents ?? [];
  const query = normalizeText(searchText);
  const managementFilter = activeFilter.startsWith("setup:");
  const group = (workspace?.groups ?? []).find((item) => item.id === activeFilter);
  const teamIndexGroup = workspaceTeamIndexes(workspace).find((item) => item.id === activeFilter);
  const groupIds = new Set((group ?? teamIndexGroup)?.agentIds ?? []);
  return agents.filter((agent) => {
    const archived = agent.status === "archived";
    if (activeFilter === "archived") {
      if (!archived) {
        return false;
      }
    } else if (archived) {
      return false;
    }
    if (managementFilter && !managementFilterMatches(agent, activeFilter)) {
      return false;
    }
    if (!managementFilter && (group || teamIndexGroup) && !groupIds.has(agent.agentId)) {
      return false;
    }
    return !query || agentSearchText(agent).includes(query);
  });
}`,
    `export function filterAgents(
  workspace: AgentConfigWorkspace | undefined,
  activeFilter: string,
  searchText: string,
  options?: {
    managementFilterMatches?: (agent: AgentConfigWorkspaceAgent, activeFilter: string) => boolean;
  },
) {
  const agents = workspace?.agents ?? [];
  const query = normalizeText(searchText);
  const managementFilter = activeFilter.startsWith("setup:");
  const group = (workspace?.groups ?? []).find((item) => item.id === activeFilter);
  const teamIndexGroup = workspaceTeamIndexes(workspace).find((item) => item.id === activeFilter);
  const groupIds = new Set((group ?? teamIndexGroup)?.agentIds ?? []);
  const matchesManagement = options?.managementFilterMatches;
  return agents.filter((agent) => {
    const archived = agent.status === "archived";
    if (activeFilter === "archived") {
      if (!archived) {
        return false;
      }
    } else if (archived) {
      return false;
    }
    if (managementFilter && matchesManagement && !matchesManagement(agent, activeFilter)) {
      return false;
    }
    if (!managementFilter && (group || teamIndexGroup) && !groupIds.has(agent.agentId)) {
      return false;
    }
    return !query || agentSearchText(agent).includes(query);
  });
}`,
  );

// Fix double export from exportFunctions already applied to filterAgents
const wsBlockFixed = wsBlock.replace(/export export function filterAgents/, "export function filterAgents");

const llmContent = `/**
 * Pure Agents LLM binding / reasoning helpers (D3).
 */
import type {
  AgentConfigDraft,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentLlmBindings,
  AgentLlmSlotDefinition,
  AgentModelChoice,
} from "../../api/types";

${fallbackBlock}

${llmBlock}
`;

const wsContent = `/**
 * Pure Agents workspace list / lightweight projection helpers (D3).
 */
import type {
  AgentBoundary,
  AgentConfigReference,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentConfigWorkspaceGroup,
  AgentInboxMessage,
  AgentRuntimeEvidence,
  AgentRuntimeEvidenceMatch,
  AgentRunHistory,
} from "../../api/types";
import type { AgentActivityTimelineItem } from "../AgentActivityHistoryPanel";
import type {
  AgentConfigWorkspaceWithTeamIndexes,
  AgentTeamIndexGroup,
} from "../agentWorkspaceCache";
import {
  agentSearchText,
  formatTimestamp,
  normalizeText,
  timestampValue,
  type RuntimeFocusEvidenceResult,
} from "./agentRouteListModel";
import { FALLBACK_AGENT_LLM_SLOTS } from "./agentRouteLlmModel";

${lightBlock}

function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return Boolean(agent?.health?.some((issue) => issue.severity === "blocking" || issue.severity === "warning"));
}

${wsBlockFixed.replace(/^export function filterAgents/, "export function filterAgents")}
`;

// Clean accidental double export export
const llmClean = llmContent.replace(/export export /g, "export ");
const wsClean = wsContent.replace(/export export /g, "export ");

fs.writeFileSync(llmPath, llmClean);
fs.writeFileSync(workspacePath, wsClean);

// Rewrite AgentsRoute: remove extracted blocks, add imports
const keepHead = lines.slice(0, Math.min(fallbackStart, llmStart));
// We need to remove FALLBACK, LIGHTWEIGHT, llm block, ws block but keep EMPTY_* and DEFAULT_*
// Structure:
// ... before FALLBACK
// EMPTY_TOOL etc stay
// DEFAULT_AGENT_RESET stays after light
// remove FALLBACK (moved)
// keep EMPTY between fallback and light
// remove LIGHTWEIGHT
// keep DEFAULT_AGENT_RESET and drafts
// remove llm+ws functions

const afterFallback = lines.slice(fallbackEnd, lightStart); // EMPTY_*
const afterLight = lines.slice(lightEnd, llmStart); // DEFAULT_AGENT_RESET + drafts + stringValue etc until agentLlmSlots
// wait stringValue and reconcile are BEFORE agentLlmSlots but after DEFAULT drafts
// lightEnd is DEFAULT_AGENT_RESET_OPTIONS start - so afterLight from lightEnd to llmStart includes DEFAULT reset + drafts + stringValue + reconcile + DEFAULT compression + bulk

// Actually order is:
// FALLBACK (remove)
// EMPTY_* (keep)
// LIGHTWEIGHT (remove)
// DEFAULT_AGENT_RESET (keep)
// stringValue, reconcile (keep)
// DEFAULT_COMPRESSION, bulk (keep)
// agentLlmSlots...selectedAgentFromList (remove)
// buildVisibleAgentColumns (keep)

const afterWs = lines.slice(wsEnd);

// Remove FALLBACK from keep: rebuild from start to fallbackStart, then EMPTY, then DEFAULT reset onwards without light
const beforeFallback = lines.slice(0, fallbackStart);
const empties = lines.slice(fallbackEnd, lightStart);
const fromDefaultReset = lines.slice(lightEnd, llmStart);

let route = [
  ...beforeFallback,
  ...empties,
  ...fromDefaultReset,
  ...afterWs,
].join("\n");

const importBlock = `
import {
  agentLlmSlotModelId,
  agentLlmSlots,
  agentMetadataWithReasoningEffort,
  agentModelById,
  agentModelReasoningEffortValues,
  agentModelSupportsReasoningEffort,
  agentReasoningEffortBySlot,
  FALLBACK_AGENT_LLM_SLOTS,
  normalizeAgentLlmBindings,
  normalizeAgentReasoningEffort,
  normalizeAgentReasoningEffortBySlot,
  pruneAgentReasoningEffortBySlot,
  sameAgentLlmBindings,
  sameAgentReasoningEffortBySlot,
  updateAgentLlmSlotBinding,
  updateAgentReasoningEffortBySlot,
  AGENT_REASONING_EFFORT_VALUES,
} from "./agents/agentRouteLlmModel";
import {
  buildActivityTimeline,
  buildLightweightAgentWorkspace,
  compactProjectionRoute,
  filterAgents,
  findRuntimeFocusEvidence,
  LIGHTWEIGHT_AGENT_CONFIG_STORAGE,
  normalizeLightweightAgent,
  referenceLabel,
  referenceRoute,
  selectedAgentFromList,
  uniqueModes,
  workspaceTeamIndexes,
} from "./agents/agentRouteWorkspaceModel";
`;

if (!route.includes("agentRouteLlmModel")) {
  route = route.replace(
    'from "./agents/agentRouteListModel";',
    `from "./agents/agentRouteListModel";\n${importBlock}`,
  );
}

// Wire filterAgents call to pass managementFilterMatches
route = route.replace(
  "() => filterAgents(workspace, activeFilter, searchText)",
  "() => filterAgents(workspace, activeFilter, searchText, { managementFilterMatches })",
);
// also non-useMemo forms
route = route.replace(
  /filterAgents\(workspace, activeFilter, searchText\)/g,
  "filterAgents(workspace, activeFilter, searchText, { managementFilterMatches })",
);

fs.writeFileSync(routePath, route);
console.log("wrote", llmPath);
console.log("wrote", workspacePath);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("removed llm", llmEnd - llmStart, "ws", wsEnd - wsStart);
