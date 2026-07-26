/**
 * M7 structure: extract Agents bulk/metadata/archive pure helpers.
 * Also moves config/persona/task draft-equals into agentRouteDraftModel.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const bulkOut = path.join(root, "web/src/routes/agents/agentRouteBulkModel.ts");
const draftPath = path.join(root, "web/src/routes/agents/agentRouteDraftModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i])) return i;
  }
  return -1;
};

const defaultBulkStart = find((l) => l.startsWith("const DEFAULT_BULK_CONFIG_DRAFT"));
const sessionToolsStart = find((l) => l.startsWith("const DEFAULT_SESSION_AGENT_PREFERRED_TOOLS"));
const safeReturnStart = find((l) => l.startsWith("function safeAgentCenterReturnTo("));
const optimisticStart = find((l) => l.startsWith("function optimisticArchivedAgent("));
const configEqualsStart = find((l) => l.startsWith("function configDraftEqualsDraft("));
const commonBulkStart = find((l) => l.startsWith("function commonBulkConfigValue("));
const metadataStart = find((l) => l.startsWith("function metadataString("));
const panesStart = find((l) => l.startsWith("function agentConfigPanes("));
const bulkSummaryStart = find((l) => l.startsWith("function agentBulkActionSummary("));
const routeExportStart = find((l) => l.startsWith("export function AgentsRoute("));

const markers = {
  defaultBulkStart,
  sessionToolsStart,
  safeReturnStart,
  optimisticStart,
  configEqualsStart,
  commonBulkStart,
  metadataStart,
  panesStart,
  bulkSummaryStart,
  routeExportStart,
};
if (Object.values(markers).some((i) => i < 0)) {
  console.error("marker missing", markers);
  process.exit(1);
}

function exportBlock(block) {
  return block
    .map((line) => {
      if (line.startsWith("function ")) return `export ${line}`;
      if (line.startsWith("const DEFAULT_BULK_CONFIG_DRAFT")) return line.replace(/^const /, "export const ");
      if (line.startsWith("const DEFAULT_BULK_CONFIG_APPLY")) return line.replace(/^const /, "export const ");
      if (line.startsWith("const metadataText = metadataString")) return line.replace(/^const /, "export const ");
      return line;
    })
    .join("\n");
}

// Draft equals → draft model
const equalsBlock = exportBlock(lines.slice(configEqualsStart, commonBulkStart));
let draft = fs.readFileSync(draftPath, "utf8");
if (!draft.includes("export function configDraftEqualsDraft")) {
  draft = draft.trimEnd() + "\n\n" + equalsBlock.replace(/export export /g, "export ") + "\n";
  // Ensure imports for draft equals deps exist
  if (!draft.includes("sameAgentLlmBindings")) {
    // already in draft model via llm model imports
  }
  fs.writeFileSync(draftPath, draft);
}

const bulkDefaults = exportBlock(lines.slice(defaultBulkStart, sessionToolsStart));
const centerReturn = exportBlock(lines.slice(safeReturnStart, optimisticStart));
const optimistic = exportBlock(lines.slice(optimisticStart, configEqualsStart));
const bulkFns = exportBlock(lines.slice(commonBulkStart, panesStart));
const bulkSummary = exportBlock(lines.slice(bulkSummaryStart, routeExportStart));

const bulkContent = `/**
 * Agents bulk config / metadata / archive pure helpers (structure M7).
 * Pure: no React hooks / Query / DOM (aside from pure path helpers).
 */
import type { AgentConfigWorkspaceAgent } from "../../api/types";
import { safeReturnToPath } from "../../app/navigationReturn";
import type {
  AgentBulkConfigApply,
  AgentBulkConfigDraft,
  AgentBulkConfigField,
} from "../AgentBulkConfigPanel";
import type { AgentBulkActionItem } from "../agentWorkspaceCache";
import { agentLabel } from "./agentRouteListModel";
import { agentLlmSlotModelId, FALLBACK_AGENT_LLM_SLOTS } from "./agentRouteLlmModel";

${bulkDefaults}

${centerReturn}

${optimistic}

${bulkFns}

${bulkSummary}
`;

fs.writeFileSync(bulkOut, bulkContent.replace(/export export /g, "export ").replace(/\n{3,}/g, "\n\n") + "\n");

// Remove from route (high first)
const removeRanges = [
  [bulkSummaryStart, routeExportStart],
  [metadataStart, panesStart], // part of bulkFns includes metadata through agentArchiveProtected; panesStart is after bulkFns
  [commonBulkStart, panesStart],
  [configEqualsStart, commonBulkStart],
  [optimisticStart, configEqualsStart],
  [safeReturnStart, optimisticStart],
  [defaultBulkStart, sessionToolsStart],
].sort((a, b) => b[0] - a[0]);

// Fix: bulkFns is commonBulkStart..panesStart which includes metadata. Don't double-remove metadata.
const uniqueRanges = [
  [bulkSummaryStart, routeExportStart],
  [commonBulkStart, panesStart],
  [configEqualsStart, commonBulkStart],
  [optimisticStart, configEqualsStart],
  [safeReturnStart, optimisticStart],
  [defaultBulkStart, sessionToolsStart],
].sort((a, b) => b[0] - a[0]);

let next = lines;
for (const [start, end] of uniqueRanges) {
  next = [...next.slice(0, start), ...next.slice(end)];
}

let route = next.join("\n");

const draftImpExtra = `  configDraftEqualsDraft,
  personaDraftEqualsDraft,
  taskDraftEqualsDraft,`;

if (!route.includes("configDraftEqualsDraft")) {
  route = route.replace(
    "  contextCompressionDraftEqualsDraft,",
    `  configDraftEqualsDraft,\n  contextCompressionDraftEqualsDraft,\n  personaDraftEqualsDraft,\n  taskDraftEqualsDraft,`,
  );
}

const bulkImp = `import {
  agentArchiveProtected,
  agentBulkActionItemNote,
  agentBulkActionSummary,
  agentBulkPurgeCleanupPending,
  agentCenterReturnLabel,
  bulkConfigApplyFields,
  bulkConfigDraftFromAgents,
  bulkConfigFieldReady,
  bulkConfigPatchFromDraft,
  bulkConfigReady,
  bulkConfigValueMixed,
  DEFAULT_BULK_CONFIG_APPLY,
  DEFAULT_BULK_CONFIG_DRAFT,
  metadataFlag,
  metadataString,
  metadataText,
  optimisticArchivedAgent,
  safeAgentCenterReturnTo,
} from "./agents/agentRouteBulkModel";
`;

if (!route.includes("agentRouteBulkModel")) {
  route = route.replace(
    'from "./agents/agentRoutePolicyDraftModel";',
    `from "./agents/agentRoutePolicyDraftModel";\n${bulkImp}`,
  );
}

fs.writeFileSync(routePath, route.replace(/\n{3,}/g, "\n\n") + "\n");
console.log("wrote", bulkOut);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("local bulkConfigReady", /function bulkConfigReady\(/.test(route));
console.log("local configDraftEquals", /function configDraftEqualsDraft\(/.test(route));
console.log("has bulk import", route.includes("agentRouteBulkModel"));
console.log("has configDraftEquals import", route.includes("configDraftEqualsDraft"));
