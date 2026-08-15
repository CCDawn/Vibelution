/**
 * M3 structure: extract Agents tool/memory/membership/runtime policy draft pure helpers.
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const routePath = path.join(root, "web/src/routes/AgentsRoute.tsx");
const outPath = path.join(root, "web/src/routes/agents/agentRoutePolicyDraftModel.ts");
const lines = fs.readFileSync(routePath, "utf8").split(/\r?\n/);

const find = (pred, from = 0) => {
  for (let i = from; i < lines.length; i += 1) {
    if (pred(lines[i], i)) return i;
  }
  return -1;
};

const typeGovStart = find((l) => l.startsWith("type AgentToolGovernanceDraft"));
const typeResetStart = find((l) => l.startsWith("type AgentResetSummary"));
const typeDraftSyncStart = find((l) => l.startsWith("type AgentDraftSyncSource"));
const typeBulkPromptStart = find((l) => l.startsWith("type AgentBulkPromptTemplateResponse"));

const draftSyncFnStart = find((l) => l.startsWith("function draftSyncSourceFromAgent("));
const optimisticStart = find((l) => l.startsWith("function optimisticArchivedAgent("));
const capabilityStart = find((l) => l.startsWith("function buildAgentCapabilityPreview("));
const configEqualsStart = find((l) => l.startsWith("function configDraftEqualsDraft("));
const membershipEqualsStart = find((l) => l.startsWith("function membershipDraftEqualsDraft("));
const personaEqualsStart = find((l) => l.startsWith("function personaDraftEqualsDraft("));
const slotStart = find((l) => l.startsWith("function slotForAgent("));
const metadataStart = find((l) => l.startsWith("function metadataString("));

const markers = {
  typeGovStart,
  typeResetStart,
  typeDraftSyncStart,
  typeBulkPromptStart,
  draftSyncFnStart,
  optimisticStart,
  capabilityStart,
  configEqualsStart,
  membershipEqualsStart,
  personaEqualsStart,
  slotStart,
  metadataStart,
};
if (Object.values(markers).some((i) => i < 0)) {
  console.error("marker missing", markers);
  process.exit(1);
}

function exportFns(block) {
  return block
    .map((line) => {
      if (line.startsWith("function ")) return `export ${line}`;
      if (line.startsWith("type ")) return `export ${line}`;
      return line;
    })
    .join("\n");
}

// Types: ToolGovernance + Delegation/Supervision aliases + DraftSync + ToolPolicyMode..CapabilityPreview
// Between typeGovStart and typeResetStart is only ToolGovernance
// type AgentDelegationPolicyDraft is between Reset and DraftSync
const typeDelegationStart = find((l) => l.startsWith("type AgentDelegationPolicyDraft"));
const typeSupervisionStart = find((l) => l.startsWith("type AgentSupervisionPolicyDraft"));

const typeBlock = exportFns([
  ...lines.slice(typeGovStart, typeResetStart), // AgentToolGovernanceDraft
  ...lines.slice(typeDelegationStart, typeDraftSyncStart), // Delegation + Supervision aliases
  ...lines.slice(typeDraftSyncStart, typeBulkPromptStart), // DraftSync through AgentCapabilityPreview
]);

const draftSyncBlock = exportFns(lines.slice(draftSyncFnStart, optimisticStart));
const capabilityBlock = exportFns(lines.slice(capabilityStart, configEqualsStart));
const membershipEqualsBlock = exportFns(lines.slice(membershipEqualsStart, personaEqualsStart));
const policyBlock = exportFns(lines.slice(slotStart, metadataStart));

const content = `/**
 * Agents tool/memory/membership/runtime policy draft mappers (structure M3).
 * Pure: no React hooks / Query / DOM.
 */
import type {
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentDelegationPolicy,
  AgentSupervisionPolicy,
  MemoryPolicy,
  ToolBundle,
  ToolPolicy,
  ToolRegistryItem,
} from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";
import type { AgentMemoryPolicyDraft } from "../AgentMemoryPolicyPanel";
import type { AgentModeMembershipDraft } from "../AgentModeMembershipPanel";
import type { AgentPersonaDraft } from "../AgentPersonaProfilePanel";
import type { AgentTaskDraft } from "../AgentTaskProfilePanel";
import {
  draftFromAgent,
  normalizeToolPolicyDraftForAgent,
  personaDraftFromAgent,
  sameStringSet,
  sortedIds,
  taskDraftFromAgent,
  type AgentToolPolicyDraft,
} from "./agentRouteDraftModel";
import { uniqueModes } from "./agentRouteWorkspaceModel";

${typeBlock}

${draftSyncBlock}

${capabilityBlock}

${membershipEqualsBlock}

${policyBlock}
`;

fs.writeFileSync(outPath, content.replace(/export export /g, "export ").replace(/\n{3,}/g, "\n\n"));

// Rebuild route: remove extracted blocks (high line numbers first is safer on single pass via filter)
const removeRanges = [
  [slotStart, metadataStart],
  [membershipEqualsStart, personaEqualsStart],
  [capabilityStart, configEqualsStart],
  [draftSyncFnStart, optimisticStart],
  [typeDraftSyncStart, typeBulkPromptStart],
  [typeDelegationStart, typeDraftSyncStart],
  [typeGovStart, typeResetStart],
].sort((a, b) => b[0] - a[0]);

let next = lines;
for (const [start, end] of removeRanges) {
  next = [...next.slice(0, start), ...next.slice(end)];
}

let route = next.join("\n");

const imp = `import {
  buildAgentCapabilityPreview,
  defaultMemoryPolicy,
  defaultToolPolicy,
  delegationPolicyDraftEqualsAgent,
  delegationPolicyDraftEqualsDraft,
  delegationPolicyDraftFromAgent,
  draftSyncSourceFromAgent,
  groupPolicyToolsByBundle,
  membershipDraftEqualsDraft,
  membershipDraftEqualsWorkspace,
  membershipDraftFromWorkspace,
  memoryPolicyDraftEqualsAgent,
  memoryPolicyDraftEqualsDraft,
  memoryPolicyDraftFromAgent,
  sharedGroupCandidates,
  supervisionPolicyDraftEqualsAgent,
  supervisionPolicyDraftEqualsDraft,
  supervisionPolicyDraftFromAgent,
  toolCategoryLabel,
  toolGovernanceDraftFromAgent,
  toolPolicyDeltaCount,
  toolPolicyDeltaFromDraft,
  toolPolicyDraftEqualsAgent,
  toolPolicyDraftEqualsDraft,
  toolPolicyDraftFromAgent,
  toolPolicyMode,
  toolPolicyModeLabel,
  toolTierLabel,
  type AgentCapabilityPreview,
  type AgentDelegationPolicyDraft,
  type AgentDraftSyncSource,
  type AgentSupervisionPolicyDraft,
  type AgentToolGovernanceDraft,
  type ToolBundleApplyMode,
  type ToolPermissionGroup,
  type ToolPolicyMode,
} from "./agents/agentRoutePolicyDraftModel";
`;

if (!route.includes("agentRoutePolicyDraftModel")) {
  route = route.replace(
    'from "./agents/agentRouteManagementModel";',
    `from "./agents/agentRouteManagementModel";\n${imp}`,
  );
}

fs.writeFileSync(routePath, route);
console.log("wrote", outPath);
console.log("AgentsRoute lines", route.split(/\n/).length);
console.log("markers", markers);
console.log("has policy import", route.includes("agentRoutePolicyDraftModel"));
console.log("local membershipDraftFromWorkspace left", /function membershipDraftFromWorkspace\(/.test(route));
console.log("local defaultToolPolicy left", /function defaultToolPolicy\(/.test(route));
