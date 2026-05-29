import { describe, expect, it } from "vitest";

import routeSource from "./AgentsRoute.tsx?raw";
import styles from "./AgentsRoute.module.css";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";

describe("AgentsRoute layout contract", () => {
  it("loads the read-only Agent config workspace endpoint", () => {
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspace>(\"/api/agents/config-workspace\")");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
  });

  it("keeps Agent management as a first-class top navigation route", () => {
    expect(routerSource).toContain('path: "agents"');
    expect(routerSource).toContain("<AgentsRoute />");
    expect(shellSource).toContain('to="/agents"');
    expect(shellSource).toContain('t("navAgents")');
    expect(routeSource).toContain('<AgentManagementNav active="agents" className={styles.managementNav} />');
    expect(routeSource.indexOf('<AgentManagementNav active="agents" className={styles.managementNav} />')).toBeGreaterThan(
      routeSource.indexOf("</header>"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="agents" className={styles.managementNav} />')).toBeLessThan(
      routeSource.indexOf("styles.summaryGrid"),
    );
  });

  it("uses filter, table, and detail panels instead of a card wall", () => {
    expect(routeSource).toContain("styles.filterPanel");
    expect(routeSource).toContain("styles.agentPanel");
    expect(routeSource).toContain("styles.detailPanel");
    expect(routeSource).toContain("styles.agentTable");
    expect(routeSource).not.toContain("agentCardGrid");
  });

  it("separates Agent filters into status, mode, and reference sections", () => {
    expect(routeSource).toContain('useState<FilterId>("active")');
    expect(routeSource).toContain("groupedFilters");
    expect(routeSource).toContain("copy.filterSections");
    expect(routeSource).toContain("copy.groupLabels");
    expect(routeSource).toContain("styles.groupSection");
    expect(routeSource).toContain("styles.groupSectionTitle");
    expect(routeSource).toContain("groupDisplayLabel(group, copy)");
    expect(styles.groupSection).toBeTruthy();
    expect(styles.groupSectionTitle).toBeTruthy();
  });

  it("shows the unified Agent card sections needed by later editing phases", () => {
    expect(routeSource).toContain("copy.model");
    expect(routeSource).toContain("copy.prompt");
    expect(routeSource).toContain("copy.tools");
    expect(routeSource).toContain("copy.memory");
    expect(routeSource).toContain("copy.runtimeStatus");
    expect(routeSource).toContain("runtimeStatusLabel");
    expect(routeSource).toContain("runtimeStatusTone");
    expect(routeSource).toContain("runtimeNextStep");
    expect(routeSource).toContain("copy.territory");
    expect(routeSource).toContain("workspaceTerritory");
    expect(routeSource).toContain("copy.context");
    expect(routeSource).toContain("copy.communication");
    expect(routeSource).toContain("copy.delegation");
    expect(routeSource).toContain("copy.modeMembership");
    expect(routeSource).toContain("copy.references");
  });

  it("edits the minimal Agent card fields through the Agent PATCH endpoint", () => {
    expect(routeSource).toContain("AgentConfigDraft");
    expect(routeSource).toContain("useMutation");
    expect(routeSource).toContain("copy.configTitle");
    expect(routeSource).toContain("displayName: payload.draft.displayName");
    expect(routeSource).toContain("profileId: payload.draft.profileId");
    expect(routeSource).toContain("promptTemplateId: payload.draft.promptTemplateId");
    expect(routeSource).toContain("toolPolicyId: payload.draft.toolPolicyId");
    expect(routeSource).toContain("memoryPolicyId: payload.draft.memoryPolicyId");
    expect(routeSource).toContain("status: payload.draft.status");
    expect(routeSource).toContain("method: \"PATCH\"");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
  });

  it("edits Agent mode membership from the same detail card", () => {
    expect(routeSource).toContain("AgentModeMembershipDraft");
    expect(routeSource).toContain("membershipDraftFromWorkspace");
    expect(routeSource).toContain("/mode-membership");
    expect(routeSource).toContain("chatDefault: event.target.checked");
    expect(routeSource).toContain("copy.researchPool");
    expect(routeSource).toContain("copy.supervisedSlot");
    expect(routeSource).toContain("copy.selfEvolutionSlot");
    expect(routeSource).toContain("queryKeys.agentModeBindings()");
    expect(routeSource).toContain("styles.toggleGrid");
  });

  it("edits Agent group room membership from the same detail card", () => {
    expect(routeSource).toContain("AgentChatRoomMembershipDraft");
    expect(routeSource).toContain("chatRoomDraftFromWorkspace");
    expect(routeSource).toContain("/chat-rooms");
    expect(routeSource).toContain("copy.chatRoomMembership");
    expect(routeSource).toContain("copy.saveChatRooms");
    expect(routeSource).toContain("queryKeys.chatRooms()");
    expect(routeSource).toContain("styles.roomMembershipList");
    expect(routeSource).toContain("styles.roomCheckField");
  });

  it("surfaces Team references as first-class Agent Center relationships", () => {
    expect(routeSource).toContain('team: "团队"');
    expect(routeSource).toContain('team: "Team"');
    expect(routeSource).toContain("summary?.teamCount");
    expect(routeSource).toContain("referenceRoute(reference)");
    expect(routeSource).toContain('`/agents/teams?team=${encodeURIComponent(reference.sourceId)}`');
    expect(routeSource).toContain("styles.referenceRouteButton");
    expect(routeSource).toContain("styles.referenceStatusStale");
  });

  it("edits Agent tool permissions from the same detail card", () => {
    expect(routeSource).toContain("AgentToolPolicyDraft");
    expect(routeSource).toContain("fetchJson<ToolRegistryPayload>(\"/api/tools\")");
    expect(routeSource).toContain("copy.toolPolicyTitle");
    expect(routeSource).toContain("allowedTools: sortedIds(payload.draft.allowedTools)");
    expect(routeSource).toContain("blockedTools: sortedIds(payload.draft.blockedTools)");
    expect(routeSource).toContain("writeScopes: sortedIds(payload.draft.writeScopes)");
    expect(routeSource).toContain("toggleToolPolicyScope(\"writeScopes\", \"shared\"");
    expect(routeSource).toContain("copy.workspaceWriteScopes");
    expect(routeSource).toContain("styles.workspaceScopePanel");
    expect(routeSource).toContain("updateToolPolicyMode(tool.name, \"allowed\")");
    expect(routeSource).toContain("updateToolPolicyMode(tool.name, \"blocked\")");
    expect(routeSource).toContain("queryKeys.tools()");
    expect(routeSource).toContain("styles.toolPermissionList");
    expect(routeSource).toContain("styles.segmentedControl");
  });

  it("edits Agent memory policy from the same detail card", () => {
    expect(routeSource).toContain("AgentMemoryPolicyDraft");
    expect(routeSource).toContain("copy.memoryPolicyTitle");
    expect(routeSource).toContain("memoryPolicy: {");
    expect(routeSource).toContain("readSharedGroups: sortedIds(payload.draft.readSharedGroups)");
    expect(routeSource).toContain("writeSharedGroups: sortedIds(payload.draft.writeSharedGroups)");
    expect(routeSource).toContain("styles.memoryPolicyGrid");
    expect(routeSource).toContain("styles.tagList");
    expect(routeSource).toContain("styles.inlineAdd");
  });

  it("organizes the Agent card into switchable panes with run history", () => {
    expect(routeSource).toContain("AgentConfigPaneId");
    expect(routeSource).toContain("agentConfigPanes(copy, selectedAgent)");
    expect(routeSource).toContain("styles.detailTabs");
    expect(routeSource).toContain("activePane === \"overview\"");
    expect(routeSource).toContain("activePane === \"config\"");
    expect(routeSource).toContain("activePane === \"policies\"");
    expect(routeSource).toContain("activePane === \"membership\"");
    expect(routeSource).toContain("activePane === \"activity\"");
    expect(routeSource).toContain("fetchJson<AgentRunHistory>");
    expect(routeSource).toContain("queryKeys.agentRuns");
    expect(routeSource).toContain("summary?.runningAgentCount");
    expect(routeSource).toContain("summary?.blockedAgentCount");
    expect(routeSource).toContain("styles.runtimePill");
    expect(routeSource).toContain("styles.runtimeFocusPanel");
    expect(routeSource).toContain("styles.runHistoryList");
  });

  it("surfaces pending Agent inbox messages from the activity pane", () => {
    expect(routeSource).toContain("AgentInboxMessage");
    expect(routeSource).toContain("queryKeys.agentMessages");
    expect(routeSource).toContain("/messages?status=pending&limit=8");
    expect(routeSource).toContain("/consume");
    expect(routeSource).toContain("consumeMessageMutation");
    expect(routeSource).toContain("copy.inboxTitle");
    expect(routeSource).toContain("styles.inboxMessageList");
    expect(routeSource).toContain("styles.inboxMessageItem");
  });

  it("summarizes runs, inbox messages, and context events in one activity timeline", () => {
    expect(routeSource).toContain("AgentActivityTimelineItem");
    expect(routeSource).toContain("buildActivityTimeline");
    expect(routeSource).toContain("activityTimeline");
    expect(routeSource).toContain("copy.activityTimeline");
    expect(routeSource).toContain("copy.runtimeFocus");
    expect(routeSource).toContain("copy.runtimeNextStep");
    expect(routeSource).toContain("copy.runtimeEvidence");
    expect(routeSource).toContain("styles.runtimeNextStep");
    expect(routeSource).toContain("styles.runtimeEvidenceHint");
    expect(styles.runtimeEvidenceHint).toBeTruthy();
    expect(routeSource).toContain("RuntimeFocusEvidenceResult");
    expect(routeSource).toContain("findRuntimeFocusEvidence");
    expect(routeSource).toContain("runtimeFocusEvidence");
    expect(routeSource).toContain("runtimeFocusEvidence.match?.runtimeSceneId");
    expect(routeSource).toContain("selectedAgent.runtimeStatus?.runId");
    expect(routeSource).toContain("selectedAgent.runtimeStatus?.sessionId");
    expect(routeSource).toContain("runtimeEvidenceReasonLabel");
    expect(routeSource).toContain("openAgentLogs(runtimeFocusEvidence.match)");
    expect(routeSource).toContain("openAgentSession");
    expect(routeSource).toContain("openAgentLogs");
    expect(routeSource).toContain("focusInboxMessage");
    expect(routeSource).toContain("/chat?session=");
    expect(routeSource).toContain('root: "runtime_scenes"');
    expect(routeSource).toContain("scene: evidence.runtimeSceneId");
    expect(routeSource).toContain("navigate(\"/logs\")");
    expect(routeSource).toContain("styles.activityTimelineList");
    expect(routeSource).toContain("styles.activityTimelineItem");
    expect(routeSource).toContain("styles.timelineActions");
    expect(routeSource).toContain("styles.inboxMessageItemFocused");
    expect(routeSource).toContain("activityTimelineItem_${item.kind}");
  });

  it("edits Agent runtime delegation and supervision policies from the activity pane", () => {
    expect(routeSource).toContain("AgentDelegationPolicyDraft");
    expect(routeSource).toContain("AgentSupervisionPolicyDraft");
    expect(routeSource).toContain("delegationPolicy: {");
    expect(routeSource).toContain("supervisionPolicy: {");
    expect(routeSource).toContain("copy.delegationPolicyTitle");
    expect(routeSource).toContain("copy.supervisionPolicyTitle");
    expect(routeSource).toContain("copy.saveRuntimePolicy");
    expect(routeSource).toContain("updateRuntimePolicyMutation");
    expect(routeSource).toContain("styles.runtimePolicyGrid");
    expect(routeSource).toContain("styles.contextModeGrid");
  });

  it("creates and safely archives Agents from the unified Agent card", () => {
    expect(routeSource).toContain("AgentCreateDraft");
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspaceAgent>(\"/api/agents\"");
    expect(routeSource).toContain("method: \"POST\"");
    expect(routeSource).toContain("createAgentMutation");
    expect(routeSource).toContain("copy.createAgent");
    expect(routeSource).toContain("styles.createAgentPanel");
    expect(routeSource).toContain("styles.createAgentGrid");
    expect(routeSource).toContain("archiveAgentMutation");
    expect(routeSource).toContain("method: \"DELETE\"");
    expect(routeSource).toContain("window.confirm");
    expect(routeSource).toContain("copy.archiveAgent");
    expect(routeSource).toContain("archivedWorkspaceCache");
    expect(routeSource).toContain("queryClient.setQueryData<AgentConfigWorkspace | undefined>");
    expect(routeSource).toContain("purgeAgentMutation");
    expect(routeSource).toContain("/purge");
    expect(routeSource).toContain("copy.purgeAgent");
    expect(routeSource).toContain("selectedAgent.status === \"archived\"");
    expect(routeSource).toContain("styles.dangerZone");
    expect(routeSource).toContain("styles.dangerButton");
  });

  it("keeps archived Agents out of non-archived filter lists immediately", () => {
    expect(routeSource).toContain('if (activeFilter === "archived")');
    expect(routeSource).toContain('} else if (archived) {');
    expect(routeSource).toContain("fallbackAgents.filter((agent) => agent.status !== \"archived\")");
    expect(routeSource).toContain("selectedAgentFromList(visibleAgents, selectedAgentId, workspace?.agents ?? [], activeFilter)");
  });

  it("separates protected core Agents from the destructive archive zone", () => {
    expect(routeSource).toContain("copy.archiveProtection");
    expect(routeSource).toContain("copy.archiveProtectionHint");
    expect(routeSource).toContain("selectedAgentProtected ? styles.protectedZone : styles.dangerZone");
    expect(routeSource).toContain("selectedAgentProtected ? <ShieldCheck");
    expect(routeSource).toContain("summary?.archivedAgentCount");
    expect(styles.protectedZone).toBeTruthy();
  });

  it("keeps the desktop workspace as three scan-friendly columns", () => {
    expect(routeSource).toContain("styles.workspace");
    expect(routeSource).toContain("styles.agentTableHead");
    expect(routeSource).toContain("styles.agentRow");
    expect(routeSource).toContain("styles.detailPanel");
  });

  it("renders every Agent as a person name plus colored functional role tag", () => {
    expect(routeSource).toContain("agentDisplayInfo(agent, lang)");
    expect(routeSource).toContain("styles.agentRoleTag");
    expect(routeSource).toContain("agentRoleTag_${display.tone}");
    expect(routeSource).toContain("display.functionLabel");
  });
});
