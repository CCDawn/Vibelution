/**
 * Extract remaining AgentsRoute mutations (persona..inbox) into useAgentWorkbenchMutations.
 * Config-draft cluster already extracted. Usage from web/:
 *   node scripts/extract-agent-remaining-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/AgentsRoute.tsx";
const outPath = "src/routes/agents/useAgentWorkbenchMutations.ts";
const src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const updatePersonaMutation = useMutation({");
const endMarker = "  const consumeAllMessagesMutation = useMutation({";
const endStart = src.indexOf(endMarker, start);
if (start < 0 || endStart < 0) {
  console.error("markers", start, endStart);
  process.exit(1);
}
const consumeMatch = src.slice(endStart).match(/^  const consumeAllMessagesMutation = useMutation\(\{[\s\S]*?\n  \}\);\n/);
if (!consumeMatch) {
  console.error("consume block match failed");
  process.exit(1);
}
const end = endStart + consumeMatch[0].length;
let body = src.slice(start, end);

const replacements = [
  ["setNotice", "options.setNotice"],
  ["chatWorkspaceCache", "options.chatWorkspaceCache"],
  ["setPersonaDraft", "options.setPersonaDraft"],
  ["setTaskDraft", "options.setTaskDraft"],
  ["draftSyncSourceRef", "options.draftSyncSourceRef"],
  ["setSelectedAgentId", "options.setSelectedAgentId"],
  ["setActivePane", "options.setActivePane"],
  ["setResettingAgentIds", "options.setResettingAgentIds"],
  ["setResetOptions", "options.setResetOptions"],
  ["setMembershipDraft", "options.setMembershipDraft"],
  ["setToolGovernanceDraft", "options.setToolGovernanceDraft"],
  ["reconcileResetDirectSession", "options.reconcileResetDirectSession"],
  ["encodeArrayBufferBase64", "options.encodeArrayBufferBase64"],
  ["updatedAgentWorkspaceCache", "options.updatedAgentWorkspaceCache"],
  ["archivedWorkspaceCache", "options.archivedWorkspaceCache"],
  ["purgedWorkspaceCache", "options.purgedWorkspaceCache"],
  ["optimisticArchivedAgent", "options.optimisticArchivedAgent"],
  ["personaProfileFromDraft", "options.personaProfileFromDraft"],
  ["personaDraftFromAgent", "options.personaDraftFromAgent"],
  ["taskProfileFromDraft", "options.taskProfileFromDraft"],
  ["taskDraftFromAgent", "options.taskDraftFromAgent"],
  ["draftSyncSourceFromAgent", "options.draftSyncSourceFromAgent"],
  ["agentLabel", "options.agentLabel"],
  ["defaultToolPolicy", "options.defaultToolPolicy"],
  ["defaultMemoryPolicy", "options.defaultMemoryPolicy"],
  ["sortedIds", "options.sortedIds"],
  ["toolPolicyDeltaFromDraft", "options.toolPolicyDeltaFromDraft"],
  ["toolGovernanceDraftFromAgent", "options.toolGovernanceDraftFromAgent"],
  ["governanceStatusLabel", "options.governanceStatusLabel"],
  ["DEFAULT_AGENT_RESET_OPTIONS", "options.DEFAULT_AGENT_RESET_OPTIONS"],
  ["stringValue", "options.stringValue"],
];

// Longer identifiers first already ordered
for (const [from, to] of replacements) {
  body = body.split(from).join(to);
}
body = body.split("options.options.").join("options.");

// Free vars that should become options.x reads
body = body
  .replaceAll(/\bworkspace\b/g, "options.getWorkspace()")
  .replaceAll("options.getWorkspace()Query", "workspaceQuery") // undo false positives if any
  .replaceAll(/\bselectedAgentId\b/g, "options.getSelectedAgentId()")
  .replaceAll(/\bactivePane\b/g, "options.getActivePane()")
  .replaceAll(/\bselectedAgent\b/g, "options.getSelectedAgent()")
  .replaceAll(/\bcopy\./g, "options.copy.")
  .replaceAll(/\blang\b/g, "options.lang");

// Fix double options and broken replacements
body = body
  .replaceAll("options.options.", "options.")
  .replaceAll("options.getSelectedAgentId()s", "options.getSelectedAgentId()") // unlikely
  .replaceAll("options.language", "language"); // if any

// Fix getSelectedAgentId() when it was selectedAgentId in wrong places like variables
// selectedAgentId in payload paths became options.getSelectedAgentId() which is correct

// Fix workspace: getWorkspace()() if double
body = body.replaceAll("options.getWorkspace()()", "options.getWorkspace()");

// AgentModeBindings type in fetchJson - import it
// AgentResetSummary - use inline type or unknown

const owners = [...body.matchAll(/const (\w+Mutation) = useMutation/g)].map((m) => m[1]);

const header = `/**
 * Remaining Agent Center write mutations (profile/lifecycle/policy/inbox).
 * Config-draft cluster lives in useAgentConfigDraftMutations.
 */
import { useMutation, useQueryClient } from "@tanstack/react-query";
import type { Dispatch, MutableRefObject, SetStateAction } from "react";

import { fetchJson } from "../../api/client";
import { queryKeys } from "../../api/queryKeys";
import type {
  AgentAvatarUploadResponse,
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentDelegationPolicy,
  AgentInboxMessage,
  AgentModeBindings,
  AgentPurgeResponse,
  AgentSupervisionPolicy,
  AgentToolGovernanceRequest,
  MemoryPolicy,
  ToolPolicy,
} from "../../api/types";
import type { AgentModeMembershipDraft } from "../AgentModeMembershipPanel";
import type { AgentMemoryPolicyDraft } from "../AgentMemoryPolicyPanel";
import type { AgentResetOptions } from "../AgentDebugResetPanel";
import { createChatWorkspaceCache } from "../chatWorkspaceCache";

type Notice = { tone: "success" | "error"; text: string };
type ChatCache = ReturnType<typeof createChatWorkspaceCache>;
type AgentResetSummary = {
  resetDirectSession?: boolean;
  previousDirectSessionId?: unknown;
  replacementDirectSessionId?: unknown;
  [key: string]: unknown;
};

export type UseAgentWorkbenchMutationsOptions = {
  lang: "zh" | "en";
  copy: Record<string, string>;
  setNotice: Dispatch<SetStateAction<Notice | null>> | ((notice: Notice) => void);
  chatWorkspaceCache: ChatCache;
  setPersonaDraft: Dispatch<SetStateAction<any>>;
  setTaskDraft: Dispatch<SetStateAction<any>>;
  draftSyncSourceRef: MutableRefObject<unknown>;
  setSelectedAgentId: Dispatch<SetStateAction<string>>;
  setActivePane: Dispatch<SetStateAction<string>>;
  setResettingAgentIds: Dispatch<SetStateAction<Set<string>>>;
  setResetOptions: Dispatch<SetStateAction<AgentResetOptions>>;
  setMembershipDraft: Dispatch<SetStateAction<AgentModeMembershipDraft>>;
  setToolGovernanceDraft: Dispatch<SetStateAction<any>>;
  getWorkspace: () => AgentConfigWorkspace | undefined;
  getSelectedAgentId: () => string;
  getActivePane: () => string;
  getSelectedAgent: () => AgentConfigWorkspaceAgent | null | undefined;
  reconcileResetDirectSession: (summary: AgentResetSummary) => void;
  encodeArrayBufferBase64: (buffer: ArrayBuffer) => string;
  updatedAgentWorkspaceCache: (current: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspace | undefined;
  archivedWorkspaceCache: (current: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspace | undefined;
  purgedWorkspaceCache: (current: AgentConfigWorkspace | undefined, agentId: string) => AgentConfigWorkspace | undefined;
  optimisticArchivedAgent: (agent: AgentConfigWorkspaceAgent) => AgentConfigWorkspaceAgent;
  personaProfileFromDraft: (draft: any) => unknown;
  personaDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  taskProfileFromDraft: (draft: any) => unknown;
  taskDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  draftSyncSourceFromAgent: (workspace: AgentConfigWorkspace | undefined, agent: AgentConfigWorkspaceAgent | null | undefined) => unknown;
  agentLabel: (agent: AgentConfigWorkspaceAgent | null | undefined) => string;
  defaultToolPolicy: (policyId?: string) => ToolPolicy;
  defaultMemoryPolicy: (policyId?: string) => MemoryPolicy;
  sortedIds: (values: string[]) => string[];
  toolPolicyDeltaFromDraft: (draft: any, agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  toolGovernanceDraftFromAgent: (agent: AgentConfigWorkspaceAgent | null | undefined) => any;
  governanceStatusLabel: (status: string, lang: "zh" | "en") => string;
  DEFAULT_AGENT_RESET_OPTIONS: AgentResetOptions;
  stringValue: (value: unknown) => string;
};

export function useAgentWorkbenchMutations(options: UseAgentWorkbenchMutationsOptions) {
  const queryClient = useQueryClient();

`;

const footer = `
  return {
${owners.map((o) => `    ${o},`).join("\n")}
  };
}
`;

writeFileSync(outPath, header + body + footer);
console.log("wrote", outPath, owners.length);

const hookCall = `  const {
${owners.map((o) => `    ${o},`).join("\n")}
  } = useAgentWorkbenchMutations({
    lang,
    copy,
    setNotice,
    chatWorkspaceCache,
    setPersonaDraft,
    setTaskDraft,
    draftSyncSourceRef,
    setSelectedAgentId,
    setActivePane,
    setResettingAgentIds,
    setResetOptions,
    setMembershipDraft,
    setToolGovernanceDraft,
    getWorkspace: () => workspace,
    getSelectedAgentId: () => selectedAgentId,
    getActivePane: () => activePane,
    getSelectedAgent: () => selectedAgent,
    reconcileResetDirectSession,
    encodeArrayBufferBase64,
    updatedAgentWorkspaceCache,
    archivedWorkspaceCache,
    purgedWorkspaceCache,
    optimisticArchivedAgent,
    personaProfileFromDraft,
    personaDraftFromAgent,
    taskProfileFromDraft,
    taskDraftFromAgent,
    draftSyncSourceFromAgent,
    agentLabel,
    defaultToolPolicy,
    defaultMemoryPolicy,
    sortedIds,
    toolPolicyDeltaFromDraft,
    toolGovernanceDraftFromAgent,
    governanceStatusLabel,
    DEFAULT_AGENT_RESET_OPTIONS,
    stringValue,
  });

`;

let route = src.slice(0, start) + hookCall + src.slice(end);
if (!route.includes("./agents/useAgentWorkbenchMutations")) {
  route = route.replace(
    'import { useAgentConfigDraftMutations } from "./agents/useAgentConfigDraftMutations";',
    'import { useAgentConfigDraftMutations } from "./agents/useAgentConfigDraftMutations";\nimport { useAgentWorkbenchMutations } from "./agents/useAgentWorkbenchMutations";',
  );
}
writeFileSync(routePath, route);
console.log("rewrote route");
