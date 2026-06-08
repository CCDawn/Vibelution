import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./AgentsRoute.tsx?raw";
import agentManagementNavSource from "./AgentManagementNav.tsx?raw";
import styles from "./AgentsRoute.module.css";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";

const stylesSource = readFileSync(new URL("./AgentsRoute.module.css", import.meta.url), "utf-8");

describe("AgentsRoute layout contract", () => {
  it("loads the read-only Agent config workspace endpoint", () => {
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspace>(\"/api/agents/config-workspace\")");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
  });

  it("uses the lightweight shell language source instead of the full app dictionary", () => {
    expect(routeSource).toContain("useShellI18n");
    expect(routeSource).toContain("const { lang } = useShellI18n()");
    expect(routeSource).not.toContain("useAppI18n");
    expect(agentManagementNavSource).toContain("useShellI18n");
    expect(agentManagementNavSource).not.toContain("useAppI18n");
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
    expect(routeSource).toContain("agent.avatarImageUrl");
    expect(routeSource).toContain("styles.agentAvatarImage");
    expect(routeSource).toContain("/api/agents/avatar-options");
    expect(routeSource).toContain("/avatar-image");
    expect(routeSource).toContain("/avatar");
    expect(routeSource).toContain("styles.avatarEditorPanel");
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

  it("labels Agent filter health counts instead of concatenating bare numbers", () => {
    expect(routeSource).toContain("function groupAriaLabel");
    expect(routeSource).toContain("aria-label={groupAriaLabel(displayLabel, group, copy, lang)}");
    expect(routeSource).toContain("{copy.healthIssueShort} {group.healthCount}");
    expect(routeSource).not.toContain("{group.healthCount ? <em>{group.healthCount}</em> : null}");
  });

  it("localizes the workspace health badge and names the avatar editor trigger", () => {
    expect(routeSource).toContain("workspaceHealthStatusLabel(healthStatus, lang)");
    expect(routeSource).toContain("workspaceHealthStatusDescription(healthStatus, summary, lang)");
    expect(routeSource).toContain("copy.workspaceHealthStatus");
    expect(routeSource).toContain("aria-label={`${copy.workspaceHealthStatus}: ${healthStatusLabel}. ${healthStatusDescription}`}");
    expect(routeSource).toContain("aria-label={copy.editAvatar}");
  });

  it("shows the unified Agent card sections needed by later editing phases", () => {
    expect(routeSource).toContain("copy.model");
    expect(routeSource).toContain("agentModelLabel");
    expect(routeSource).toContain("buildAgentModelChoices");
    expect(routeSource).not.toContain("modelProfileSelectValue");
    expect(routeSource).toContain("copy.prompt");
    expect(routeSource).toContain("promptTemplateDisplayName(agent.promptTemplate, agent.promptTemplateId, lang)");
    expect(routeSource).toContain("promptTemplateDisplayName(selectedAgent.promptTemplate, selectedAgent.promptTemplateId, lang)");
    expect(routeSource).toContain("promptTemplateOptionLabel(template, lang)");
    expect(routeSource).toContain('"research ceo": "科研负责人"');
    expect(routeSource).not.toContain("<span>{agent.promptTemplate?.name || agent.promptTemplateId || \"-\"}</span>");
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

  it("shows LLM names in model selectors instead of role-prefixed profile labels", () => {
    expect(routeSource).toContain("AgentModelChoice");
    expect(routeSource).toContain("model.model");
    expect(routeSource).toContain("model.modelId");
    expect(routeSource).toContain("function agentModelChoiceAllowed");
    expect(routeSource).toContain("!text.includes(\"image2\")");
    expect(routeSource).toContain("buildAgentModelChoices(workspace?.agentModelChoices ?? [])");
    expect(routeSource).toContain("buildAgentSlotModelChoicesWithCurrent");
    expect(routeSource).toContain("selectedSlotModelId");
    expect(routeSource).toContain("agentLlmSlots(workspace)");
    expect(routeSource).toContain("workspace?.agentLlmSlots?.length");
    expect(routeSource).toContain("key: model.modelId");
    expect(routeSource).toContain("agentDialogueModelDisplay(agent, lang)");
    expect(routeSource).toContain("unresolved_model_reference_dialogue");
    expect(routeSource).toContain("模型库未注册");
    expect(routeSource).toContain("当前槽位不可选");
    expect(routeSource).toContain("当前绑定，模型库未注册");
    expect(routeSource).toContain("current binding, unavailable for this slot");
    expect(routeSource).toContain("agentModelChoices.map((model)");
    expect(routeSource).toContain("value={agentLlmSlotModelId(createDraft.llmBindings, FALLBACK_AGENT_LLM_SLOTS[0])}");
    expect(routeSource).toContain("value={selectedSlotModelId}");
    expect(routeSource).toContain("styles.llmSlotGrid");
    expect(routeSource).toContain("llmSlotsHint");
    expect(routeSource).toContain("按 Agent 自己配置对话、心智模型、摘要、子 Agent 和视觉等 LLM 槽位");
    expect(routeSource).toContain("设置页只维护模型库资产");
    expect(routeSource).toContain("title={model.modelLabel || model.modelId}");
    expect(routeSource).toContain("{model.label}");
    expect(routeSource).not.toContain("buildModelProfileChoices(workspace?.modelProfiles ?? [])");
    expect(routeSource).not.toContain("modelProfileChoices.map((profile)");
    expect(routeSource).not.toContain("value={createDraft.profileId}");
    expect(routeSource).not.toContain("value={configDraft.profileId}");
    expect(routeSource).not.toContain("profileByModel");
    expect(routeSource).not.toContain("profileByLabel");
    expect(routeSource).not.toContain("choices.has(labelKey)");
    expect(routeSource).not.toContain("profileIds: [profile.profileId]");
    expect(routeSource).not.toContain("title={profile.detail || profile.modelId}");
    expect(routeSource).not.toContain("{agent.modelProfile?.label || agent.profileId || \"-\"}");
    expect(routeSource).not.toContain("{profile.label || profile.profileId} · {profile.model || profile.providerKind || \"-\"}");
  });

  it("keeps permanent Agent deletion behind the archived-state safety gate", () => {
    expect(routeSource).toContain('const canPurgeAgent = Boolean(selectedAgent?.agentId && selectedAgent.status === "archived" && !selectedAgentProtected)');
    expect(routeSource).toContain('agent.status !== "archived"');
    expect(routeSource).toContain("copy.bulkSkippedActive");
    expect(routeSource).toContain("selectedAgent.status !== \"archived\" ? (");
    expect(routeSource).toContain("className={styles.secondaryButton}");
    expect(routeSource).toContain("onClick={archiveSelectedAgent}");
    expect(routeSource).toContain("onClick={purgeSelectedAgent}");
    expect(routeSource).toContain("已彻底删除归档 Agent");
    expect(routeSource).not.toContain("const canPurgeAgent = Boolean(selectedAgent?.agentId && !selectedAgentProtected)");
  });

  it("updates mode membership locally after saving so bindings stay aligned", () => {
    expect(routeSource).toContain("fetchJson<AgentModeBindings>");
    expect(routeSource).toContain("queryClient.setQueryData<AgentConfigWorkspace | undefined>");
    expect(routeSource).toContain("modeBindings: payload.modes ?? current.modeBindings");
    expect(routeSource).toContain("setMembershipDraft(variables.draft)");
  });

  it("routes membership guidance to the team surface and not just the config pane", () => {
    expect(routeSource).toContain("route: agent?.agentId ? `/teams?agent=${encodeURIComponent(agent.agentId)}` : \"/teams\"");
    expect(routeSource).toContain("void navigate(action.route)");
    expect(routeSource).toContain("setActivePane(action.pane)");
    expect(routeSource).toContain("copy.nextSetupMembership");
  });

  it("keeps tool and runtime completeness strict enough to avoid false positives", () => {
    expect(routeSource).toContain("function hasToolPolicyConfiguration(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain("policy?.blockedTools?.length");
    expect(routeSource).toContain("function agentHasRuntimeSignal(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain("const runtimeState = String(agent?.runtimeStatus?.state || \"\").trim()");
    expect(routeSource).toContain("runtimeState && runtimeState !== \"idle\"");
    expect(routeSource).toContain("count((agent) => agent.health.length > 0)");
    expect(routeSource).toContain("return agent.health.length > 0;");
  });

  it("creates Agents through tool bundle presets instead of raw tool strings", () => {
    expect(routeSource).toContain("DEFAULT_SESSION_AGENT_ALLOWED_TOOLS");
    expect(routeSource).toContain("\"conversation_log_inspect_tool\"");
    expect(routeSource).toContain("allowedTools: DEFAULT_SESSION_AGENT_ALLOWED_TOOLS.join(\", \")");
    expect(routeSource).toContain("selectedToolBundleIds: string[]");
    expect(routeSource).toContain("function defaultCreateToolBundleIds");
    expect(routeSource).toContain('const preferred = workSession ? ["core", "coding", "memory_context"] : ["core", "research", "collaboration"]');
    expect(routeSource).toContain("function toolBundleIdsForModeChange");
    expect(routeSource).toContain("const hasCustomSelection = draft.selectedToolBundleIds.length > 0 && !sameStringSet(draft.selectedToolBundleIds, currentDefaults)");
    expect(routeSource).toContain("selectedToolBundleIds: toolBundleIdsForModeChange(createDraft, primaryMode, toolBundles)");
    expect(routeSource).toContain("function toolBundleSelectionToPolicy");
    expect(routeSource).toContain("function createToolBundleSummary");
    expect(routeSource).toContain("createToolBundleSummaryValue");
    expect(routeSource).toContain("copy.createAgentToolBundles");
    expect(routeSource).toContain("copy.createAgentToolBundlePreview");
    expect(routeSource).toContain("creationToolBundleIds: sortedIds(draft.selectedToolBundleIds)");
    expect(routeSource).toContain("toolPolicy: {");
    expect(routeSource).toContain("styles.workspaceCreating");
    expect(routeSource).toContain("styles.agentPanelCreating");
    expect(routeSource).not.toContain("toolPolicy: workSession ? {} : {");
    expect(styles.createToolBundleGrid).toBeTruthy();
    expect(styles.createToolBundleOption).toBeTruthy();
    expect(styles.createToolBundleSelected).toBeTruthy();
    expect(styles.createToolBundlePreview).toBeTruthy();
    expect(styles.workspaceCreating).toBeTruthy();
    expect(styles.agentPanelCreating).toBeTruthy();
  });

  it("uses user-facing Chinese labels instead of internal workspace terms", () => {
    expect(routeSource).toContain("系统编号");
    expect(routeSource).toContain("工具能力");
    expect(routeSource).toContain("记忆设置");
    expect(routeSource).toContain("工作空间");
    expect(routeSource).toContain("私人工作区");
    expect(routeSource).toContain("共享资料区");
    expect(routeSource).toContain("默认保存位置");
    expect(routeSource).toContain("使用位置");
    expect(routeSource).toContain("协作助手");
    expect(routeSource).toContain("工具能力模板");
    expect(routeSource).toContain("记忆范围模板");
    expect(routeSource).not.toContain("后台编号");
    expect(routeSource).not.toContain("工具权限");
    expect(routeSource).not.toContain("记忆策略");
    expect(routeSource).not.toContain("工作领地");
    expect(routeSource).not.toContain("私有写入根");
    expect(routeSource).not.toContain("共享读取区");
    expect(routeSource).not.toContain("默认写入边界");
    expect(routeSource).not.toContain("模式归属");
    expect(routeSource).not.toContain("策略注册表待接入");
    expect(routeSource).not.toContain("记忆边界模板");
    expect(routeSource).not.toContain("工具权限模板");
  });

  it("edits the minimal Agent card fields through the Agent PATCH endpoint", () => {
    expect(routeSource).toContain("AgentConfigDraft");
    expect(routeSource).toContain("useMutation");
    expect(routeSource).toContain("copy.configTitle");
    expect(routeSource).toContain("copy.configGuideTitle");
    expect(routeSource).toContain("copy.configGuideBoundaryHint");
    expect(routeSource).toContain("copy.toolPolicyPickerHint");
    expect(routeSource).toContain("copy.memoryPolicyPickerHint");
    expect(routeSource).toContain("styles.configGuidePanel");
    expect(routeSource).toContain("displayName: payload.draft.displayName");
    expect(routeSource).toContain("llmBindings: normalizeAgentLlmBindings(payload.draft.llmBindings)");
    expect(routeSource).toContain("promptTemplateId: payload.draft.promptTemplateId");
    expect(routeSource).toContain("toolPolicyId: payload.draft.toolPolicyId");
    expect(routeSource).toContain("memoryPolicyId: payload.draft.memoryPolicyId");
    expect(routeSource).toContain("status: payload.draft.status");
    expect(routeSource).toContain("method: \"PATCH\"");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(styles.configGuidePanel).toBeTruthy();
    expect(styles.healthGuidePanel).toBeTruthy();
  });

  it("explains Agent health states with reason and next action instead of a bare hint pill", () => {
    expect(routeSource).toContain('return lang === "zh" ? "可优化" : "Optional"');
    expect(routeSource).toContain("function issueSummary");
    expect(routeSource).toContain("function issueNextStep");
    expect(routeSource).toContain("styles.healthCell");
    expect(routeSource).toContain("styles.detailHealthStatus");
    expect(routeSource).toContain("copy.healthNextStep");
    expect(routeSource).toContain("issueSummary(agent.health, lang)");
    expect(routeSource).toContain("issueNextStep(selectedAgent.health, lang)");
    expect(styles.healthCell).toBeTruthy();
    expect(styles.detailHealthStatus).toBeTruthy();
  });

  it("edits Agent persona profile from AgentDirectory without recommendation automation", () => {
    expect(routeSource).toContain("AgentPersonaDraft");
    expect(routeSource).toContain("personaProfileFromDraft");
    expect(routeSource).toContain("personaProfile: personaProfileFromDraft(payload.draft)");
    expect(routeSource).toContain("updatedAgentWorkspaceCache");
    expect(routeSource).toContain("setPersonaDraft(personaDraftFromAgent(agent))");
    expect(routeSource).toContain("draftSyncSourceRef.current = draftSyncSourceFromAgent(workspace, agent)");
    expect(routeSource).toContain("copy.personaTitle");
    expect(routeSource).toContain("copy.gender");
    expect(routeSource).toContain("copy.age");
    expect(routeSource).toContain("copy.communicationStyle");
    expect(routeSource).toContain("copy.collaborationPreference");
    expect(routeSource).toContain("copy.identityNotes");
    expect(routeSource).toContain("styles.fieldWide");
    expect(routeSource).toContain("updatePersonaMutation");
    expect(routeSource).not.toContain("recommendAgents");
    expect(styles.fieldWide).toBeTruthy();
  });

  it("protects unsaved Agent drafts from workspace polling refreshes", () => {
    expect(routeSource).toContain("AgentDraftSyncSource");
    expect(routeSource).toContain("draftSyncSourceRef");
    expect(routeSource).toContain("draftSyncSourceFromAgent(workspace, selectedAgent)");
    expect(routeSource).toContain("const agentChanged = previousSource?.agentId !== nextSource.agentId");
    expect(routeSource).toContain("configDraftEqualsDraft(current, previousSource.config) ? nextSource.config : current");
    expect(routeSource).toContain("personaDraftEqualsDraft(current, previousSource.persona) ? nextSource.persona : current");
    expect(routeSource).toContain("taskDraftEqualsDraft(current, previousSource.task) ? nextSource.task : current");
    expect(routeSource).toContain("toolPolicyDraftEqualsDraft(current, previousSource.toolPolicy) ? nextSource.toolPolicy : current");
    expect(routeSource).toContain("memoryPolicyDraftEqualsDraft(current, previousSource.memoryPolicy) ? nextSource.memoryPolicy : current");
    expect(routeSource).toContain("delegationPolicyDraftEqualsDraft(current, previousSource.delegationPolicy) ? nextSource.delegationPolicy : current");
    expect(routeSource).toContain("supervisionPolicyDraftEqualsDraft(current, previousSource.supervisionPolicy) ? nextSource.supervisionPolicy : current");
    expect(routeSource).not.toContain("}, [selectedAgent?.agentId, workspace?.generatedAt]);");
  });

  it("edits Agent task profile from AgentDirectory without automatic routing", () => {
    expect(routeSource).toContain("AgentTaskDraft");
    expect(routeSource).toContain("taskProfileFromDraft");
    expect(routeSource).toContain("taskProfile: taskProfileFromDraft(payload.draft)");
    expect(routeSource).toContain("copy.taskTitle");
    expect(routeSource).toContain("copy.mission");
    expect(routeSource).toContain("copy.taskTypes");
    expect(routeSource).toContain("copy.responsibilities");
    expect(routeSource).toContain("copy.preferredTasks");
    expect(routeSource).toContain("copy.successCriteria");
    expect(routeSource).toContain("copy.handoffNotes");
    expect(routeSource).toContain("updateTaskMutation");
    expect(routeSource).not.toContain("autoRouteAgent");
  });

  it("edits Agent mode membership from the same detail card", () => {
    expect(routeSource).toContain("AgentModeMembershipDraft");
    expect(routeSource).toContain("membershipDraftFromWorkspace");
    expect(routeSource).toContain("/mode-membership");
    expect(routeSource).toContain("chatDefault: event.target.checked");
    expect(routeSource).toContain("copy.researchPool");
    expect(routeSource).toContain("copy.supervisedSlot");
    expect(routeSource).toContain("copy.selfEvolutionSlot");
    expect(routeSource).toContain("chatWorkspaceCache.afterAgentWorkspaceChanged()");
    expect(routeSource).toContain("styles.toggleGrid");
  });

  it("shows Agent group room membership as read-only references", () => {
    expect(routeSource).toContain("copy.chatRoomMembership");
    expect(routeSource).toContain("只读引用");
    expect(routeSource).toContain("Read-only");
    expect(routeSource).toContain("selectedAgent.references.filter((reference) => reference.kind === \"chat_room\").length");
    expect(routeSource).toContain("styles.roomMembershipList");
    expect(routeSource).toContain("styles.roomCheckField");
    expect(routeSource).toContain("navigate(`/chat?room=${encodeURIComponent(room.roomId)}`)");
    expect(routeSource).toContain("打开群聊");
    expect(routeSource).toContain("群聊成员关系在对话页的群设置中维护；团队关联群聊由团队页同步。");
    expect(routeSource).not.toContain("AgentChatRoomMembershipDraft");
    expect(routeSource).not.toContain("chatRoomDraftFromWorkspace");
    expect(routeSource).not.toContain("updateChatRoomsMutation");
    expect(routeSource).not.toContain("chatWorkspaceCache.afterAgentChatRoomsChanged()");
    expect(routeSource).not.toContain("copy.saveChatRooms");
  });

  it("surfaces Team references as first-class Agent Center relationships", () => {
    expect(routeSource).toContain('team: "团队"');
    expect(routeSource).toContain('team: "Team"');
    expect(routeSource).toContain("summary?.teamCount");
    expect(routeSource).toContain("referenceRoute(reference)");
    expect(routeSource).toContain('`/teams?team=${encodeURIComponent(reference.sourceId)}`');
    expect(routeSource).toContain("styles.referenceRouteButton");
    expect(routeSource).toContain("styles.referenceStatusStale");
  });

  it("edits Agent tool permissions from the same detail card", () => {
    expect(routeSource).toContain("AgentToolPolicyDraft");
    expect(routeSource).toContain("AgentCapabilityPreview");
    expect(routeSource).toContain("buildAgentCapabilityPreview");
    expect(routeSource).toContain("fetchJson<ToolRegistryPayload>(\"/api/tools\")");
    expect(routeSource).toContain("copy.toolPolicyTitle");
    expect(routeSource).toContain("allowedTools: sortedIds(payload.draft.allowedTools)");
    expect(routeSource).toContain("preferredTools: sortedIds(payload.draft.preferredTools)");
    expect(routeSource).toContain("blockedTools: sortedIds(payload.draft.blockedTools)");
    expect(routeSource).toContain("writeScopes: sortedIds(payload.draft.writeScopes)");
    expect(routeSource).toContain("const toolBundles = toolsQuery.data?.toolBundles ?? []");
    expect(routeSource).toContain("applyToolBundle(bundle, \"merge\")");
    expect(routeSource).toContain("applyToolBundle(bundle, \"replace\")");
    expect(routeSource).toContain("copy.toolBundlesTitle");
    expect(routeSource).toContain("copy.applyBundle");
    expect(routeSource).toContain("copy.replaceWithBundle");
    expect(routeSource).toContain("copy.preferredTools");
    expect(routeSource).toContain("styles.toolBundlePanel");
    expect(routeSource).toContain("styles.toolBundleItem");
    expect(routeSource).toContain("toggleToolPolicyScope(\"writeScopes\", \"shared\"");
    expect(routeSource).toContain("copy.workspaceWriteScopes");
    expect(routeSource).toContain("styles.workspaceScopePanel");
    expect(routeSource).toContain("groupPolicyToolsByBundle");
    expect(routeSource).toContain("visiblePolicyToolGroups");
    expect(routeSource).toContain("tool.bundleIds");
    expect(routeSource).toContain("toolCategoryLabel");
    expect(routeSource).toContain("toolTierLabel");
    expect(routeSource).toContain("copy.toolCategoryCount");
    expect(routeSource).toContain("const toolsWorkspaceNeeded = createOpen || activePane === \"config\"");
    expect(routeSource).toContain("enabled: toolsWorkspaceNeeded");
    expect(routeSource).toContain("refetchInterval: toolsWorkspaceNeeded ? resolvePollingInterval(pageVisible, 15_000) : false");
    expect(routeSource).toContain("按工具包配置");
    expect(routeSource).toContain("同一工具只会保存一份授权状态");
    expect(routeSource).toContain("copy.capabilityPreviewTitle");
    expect(routeSource).toContain("capabilityPreview.highRiskAllowed");
    expect(routeSource).toContain("styles.capabilityPreviewPanel");
    expect(routeSource).toContain("styles.toolPermissionGroup");
    expect(routeSource).toContain("styles.toolPermissionGroupHeader");
    expect(routeSource).toContain("styles.toolPermissionMeta");
    expect(routeSource).toContain("updateToolPolicyMode(tool.name, \"allowed\")");
    expect(routeSource).toContain("updateToolPolicyMode(tool.name, \"blocked\")");
    expect(routeSource).toContain("queryKeys.tools()");
    expect(routeSource).toContain("styles.toolPermissionList");
    expect(routeSource).toContain("styles.segmentedControl");
    expect(routeSource.indexOf("copy.workspaceWriteScopes")).toBeLessThan(routeSource.indexOf("copy.toolBundlesTitle"));
    expect(routeSource.indexOf("copy.toolBundlesTitle")).toBeLessThan(routeSource.indexOf("copy.toolSearch"));
    expect(styles.toolBundlePanel).toBeTruthy();
    expect(styles.toolBundleItem).toBeTruthy();
    expect(styles.toolPermissionGroup).toBeTruthy();
    expect(styles.toolPermissionGroupHeader).toBeTruthy();
    expect(styles.toolPermissionMeta).toBeTruthy();
    expect(styles.capabilityPreviewPanel).toBeTruthy();
  });

  it("surfaces advisor tool-governance requests without bypassing ToolPolicy", () => {
    expect(routeSource).toContain("AgentToolGovernanceRequest");
    expect(routeSource).toContain("toolGovernanceDraftFromAgent");
    expect(routeSource).toContain("toolPolicyDeltaFromDraft");
    expect(routeSource).toContain("/tool-governance-requests");
    expect(routeSource).toContain("copy.toolGovernanceTitle");
    expect(routeSource).toContain("copy.toolGovernancePending");
    expect(routeSource).toContain("copy.toolGovernanceApprove");
    expect(routeSource).toContain("copy.toolGovernanceReject");
    expect(routeSource).toContain("createToolGovernanceMutation");
    expect(routeSource).toContain("resolveToolGovernanceMutation");
    expect(routeSource).toContain("styles.toolGovernanceList");
    expect(routeSource).toContain("styles.toolGovernanceItem");
    expect(styles.toolGovernanceList).toBeTruthy();
    expect(styles.toolGovernanceItem).toBeTruthy();
  });

  it("edits Agent memory policy from the same detail card", () => {
    expect(routeSource).toContain("AgentMemoryPolicyDraft");
    expect(routeSource).toContain("copy.memoryPolicyTitle");
    expect(routeSource).toContain("memoryPolicy: {");
    expect(routeSource).toContain("readSharedGroups: sortedIds(payload.draft.readSharedGroups)");
    expect(routeSource).toContain("writeSharedGroups: sortedIds(payload.draft.writeSharedGroups)");
    expect(routeSource).toContain("readKnowledgeBaseIds: sortedIds(payload.draft.readKnowledgeBaseIds)");
    expect(routeSource).toContain("proposeKnowledgeBaseIds: sortedIds(payload.draft.proposeKnowledgeBaseIds)");
    expect(routeSource).toContain("reviewKnowledgeBaseIds: sortedIds(payload.draft.reviewKnowledgeBaseIds)");
    expect(routeSource).toContain("rateKnowledgeBaseIds: sortedIds(payload.draft.rateKnowledgeBaseIds)");
    expect(routeSource).toContain("copy.readKnowledgeBaseIds");
    expect(routeSource).toContain("copy.proposeKnowledgeBaseIds");
    expect(routeSource).toContain("copy.reviewKnowledgeBaseIds");
    expect(routeSource).toContain("copy.rateKnowledgeBaseIds");
    expect(routeSource).toContain("styles.memoryPolicyGrid");
    expect(routeSource).toContain("styles.tagList");
    expect(routeSource).toContain("styles.inlineAdd");
  });

  it("organizes the Agent card into three switchable panes with run history", () => {
    expect(routeSource).toContain("AgentConfigPaneId");
    expect(routeSource).toContain('type AgentConfigPaneId = "overview" | "config" | "activity"');
    expect(routeSource).toContain("agentConfigPanes(copy, selectedAgent)");
    expect(routeSource).toContain("AgentManagementBrief");
    expect(routeSource).toContain("buildAgentManagementBrief(selectedAgent, copy, lang)");
    expect(routeSource).toContain("copy.managementBriefTitle");
    expect(routeSource).toContain("copy.nextActionsTitle");
    expect(routeSource).toContain("styles.managementBriefPanel");
    expect(routeSource).toContain("styles.nextActionList");
    expect(routeSource).toContain("styles.detailTabs");
    expect(routeSource).toContain("activePane === \"overview\"");
    expect(routeSource).toContain("activePane === \"config\"");
    expect(routeSource).not.toContain("activePane === \"policies\"");
    expect(routeSource).not.toContain("activePane === \"membership\"");
    expect(routeSource).toContain("copy.toolPolicyTitle");
    expect(routeSource).toContain("copy.memoryPolicyTitle");
    expect(routeSource).toContain("copy.membershipTitle");
    expect(routeSource).toContain("activePane === \"activity\"");
    expect(routeSource).toContain("fetchJson<AgentRunHistory>");
    expect(routeSource).toContain("queryKeys.agentRuns");
    expect(routeSource).toContain("summary?.runningAgentCount");
    expect(routeSource).toContain("summary?.blockedAgentCount");
    expect(routeSource).toContain("styles.runtimePill");
    expect(routeSource).toContain("styles.runtimeFocusPanel");
    expect(routeSource).toContain("styles.runHistoryList");
    expect(routeSource).toContain("styles.boundarySummaryGrid");
    expect(styles.managementBriefPanel).toBeTruthy();
    expect(styles.nextActionList).toBeTruthy();
    expect(styles.boundarySummaryGrid).toBeTruthy();
    expect(styles.detailTabs).toBeTruthy();
  });

  it("includes work-session Agent setup copy for model instructions and workspace boundaries", () => {
    expect(routeSource).toContain("function isWorkSessionCreateDraft");
    expect(routeSource).toContain("const createDraftIsWorkSession = isWorkSessionCreateDraft(createDraft)");
    expect(routeSource).toContain("const workSession = isWorkSessionCreateDraft(draft)");
    expect(routeSource).toContain("const sectionOrder = [\"status\", \"boundary\", \"mode\", \"reference\"] as const");
    expect(routeSource).toContain("copy.managementModelPrompt");
    expect(routeSource).toContain("copy.managementWorkspace");
    expect(routeSource).toContain("copy.nextSetupModelPrompt");
    expect(routeSource).toContain("copy.nextSetupWorkspace");
    expect(routeSource).toContain("Model / instructions");
    expect(routeSource).toContain("Check workspace boundary");
    expect(routeSource).toContain("配置模型与项目指令");
    expect(routeSource).toContain("检查工作区边界");
    expect(routeSource).toContain("Work-session Agents");
    expect(routeSource).toContain("Team role Agents");
    expect(routeSource).toContain("会话工作 Agent");
    expect(routeSource).toContain("团队角色 Agent");
  });

  it("keeps persona, task, and membership configuration out of work-session Agents", () => {
    expect(routeSource).toContain("selectedAgentRequiresPersona");
    expect(routeSource).toContain("selectedAgentRequiresTask");
    expect(routeSource).toContain("selectedAgentRequiresTeamMembership");
    expect(routeSource).toContain("{selectedAgentRequiresPersona ? (");
    expect(routeSource).toContain("{selectedAgentRequiresTask ? (");
    expect(routeSource).toContain("{selectedAgentRequiresTeamMembership ? (");
    expect(routeSource).toContain("{!createDraftIsWorkSession ? (");
    expect(routeSource).toContain("const roleKey = workSession ? \"\" : draft.roleKey.trim()");
    expect(routeSource).toContain("const personaProfile = workSession");
    expect(routeSource).toContain("const taskProfile = workSession");
  });

  it("adds task-oriented Agent management filters for configuration gaps", () => {
    expect(routeSource).toContain("buildManagementFilterGroups");
    expect(routeSource).toContain("managementFilterMatches");
    expect(routeSource).toContain("activeFilter.startsWith(\"setup:\")");
    expect(routeSource).toContain("copy.filterSections.management");
    expect(routeSource).toContain("copy.managementFilterMissingPersona");
    expect(routeSource).toContain("copy.managementFilterMissingTask");
    expect(routeSource).toContain("copy.managementFilterMissingTools");
    expect(routeSource).toContain("copy.managementFilterNoTeam");
    expect(routeSource).toContain("copy.managementFilterPendingInbox");
    expect(routeSource).toContain("copy.managementFilterMaintenance");
  });

  it("surfaces pending Agent inbox messages from the activity pane", () => {
    expect(routeSource).toContain("AgentInboxMessage");
    expect(routeSource).toContain("queryKeys.agentMessages");
    expect(routeSource).toContain("/messages?status=pending&limit=8");
    expect(routeSource).toContain("/consume");
    expect(routeSource).toContain("consumeMessageMutation");
    expect(routeSource).toContain("consumeAllMessagesMutation");
    expect(routeSource).toContain("/messages/consume-all");
    expect(routeSource).toContain("copy.handleInboxNow");
    expect(routeSource).toContain("copy.consumeAllMessages");
    expect(routeSource).toContain("copy.inboxTitle");
    expect(routeSource).toContain("const selectedAgentInboxPendingCount = selectedAgent?.agentInboxPendingCount ?? agentMessagesQuery.data?.length ?? 0");
    expect(routeSource).toContain("<h3>{copy.inboxTitle}: {selectedAgentInboxPendingCount}</h3>");
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
    expect(routeSource).toContain("purgedWorkspaceCache");
    expect(routeSource).toContain("queryClient.setQueryData<AgentConfigWorkspace | undefined>");
    expect(routeSource).toContain("purgeAgentMutation");
    expect(routeSource).toContain("/purge");
    expect(routeSource).toContain("copy.purgeAgent");
    expect(routeSource).toContain("copy.maintenanceTitle");
    expect(routeSource).toContain("styles.maintenanceIntro");
    expect(routeSource).toContain("selectedAgent.status === \"archived\"");
    expect(routeSource).toContain("styles.dangerZone");
    expect(routeSource).toContain("styles.dangerButton");
    expect(styles.maintenanceIntro).toBeTruthy();
  });

  it("offers a governed per-Agent debug reset without archive or membership cleanup", () => {
    expect(routeSource).toContain("AgentResetOptions");
    expect(routeSource).toContain("resetAgentMutation");
    expect(routeSource).toContain("resettingAgentIds");
    expect(routeSource).toContain("selectedAgentResetPending");
    expect(routeSource).toContain("new Set(current)");
    expect(routeSource).toContain("next.add(payload.agentId)");
    expect(routeSource).toContain("next.delete(payload.agentId)");
    expect(routeSource).toContain("/reset");
    expect(routeSource).toContain("method: \"POST\"");
    expect(routeSource).toContain("copy.resetAgent");
    expect(routeSource).toContain("copy.resetClearRuntimeState");
    expect(routeSource).toContain("copy.resetClearRuntimeStateHint");
    expect(routeSource).toContain("copy.resetDirectSession");
    expect(routeSource).toContain("copy.resetDirectSessionHint");
    expect(routeSource).toContain("copy.resetPersonaProfile");
    expect(routeSource).toContain("copy.resetPersonaProfileHint");
    expect(routeSource).toContain("copy.resetTaskProfile");
    expect(routeSource).toContain("copy.resetTaskProfileHint");
    expect(routeSource).toContain("copy.resetToolPolicy");
    expect(routeSource).toContain("copy.resetToolPolicyHint");
    expect(routeSource).toContain("copy.resetMemoryPolicy");
    expect(routeSource).toContain("copy.resetMemoryPolicyHint");
    expect(routeSource).toContain("copy.resetRuntimePolicy");
    expect(routeSource).toContain("copy.resetRuntimePolicyHint");
    expect(routeSource).toContain("styles.resetOptionField");
    expect(routeSource).toContain("queryKeys.agentRuntimeEvidence(agent.agentId)");
    expect(routeSource).toContain("selectedAgent.status !== \"archived\"");
    expect(routeSource).toContain("disabled={!canResetAgent || selectedAgentResetPending}");
    expect(routeSource).toContain("selectedAgentResetPending ? copy.resettingAgent : copy.resetAgent");
    expect(routeSource).not.toContain("!canResetAgent || resetAgentMutation.isPending");
    expect(styles.resetZone).toBeTruthy();
    expect(styles.resetOptionGrid).toBeTruthy();
    expect(styles.resetOptionField).toBeTruthy();
  });

  it("keeps per-Agent avatar, governance, and inbox actions scoped to their target object", () => {
    expect(routeSource).toContain("selectedAgentAvatarUpdatePending");
    expect(routeSource).toContain("selectedAgentAvatarUploadPending");
    expect(routeSource).toContain("selectedAgentConsumeAllPending");
    expect(routeSource).toContain("updateAvatarMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("uploadAvatarMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("(current) => updatedAgentWorkspaceCache(current, agent)");
    expect(routeSource).toContain("(current) => updatedAgentWorkspaceCache(current, result.agent)");
    expect(routeSource).toContain("consumeAllMessagesMutation.variables?.agentId === selectedAgent?.agentId");
    expect(routeSource).toContain("resolveToolGovernanceMutation.variables?.requestId === request.requestId");
    expect(routeSource).toContain("consumeMessageMutation.variables?.messageId === messageId");
    expect(routeSource).toContain("queryKeys.agentMessages(variables.agentId, \"pending\")");
    expect(routeSource).not.toContain("if (selectedAgent?.agentId) {\n        void queryClient.invalidateQueries({ queryKey: queryKeys.agentMessages(selectedAgent.agentId, \"pending\") });");
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
    expect(styles.workspace).toBeTruthy();
    expect(stylesSource).toContain("grid-template-columns: minmax(214px, 268px) minmax(430px, 1.08fr) minmax(330px, 0.86fr)");
    expect(stylesSource).toContain("@media (max-width: 1040px)");
    expect(stylesSource).not.toContain("@media (max-width: 1280px)");
    expect(stylesSource).toContain("grid-auto-rows: minmax(260px, auto)");
    expect(stylesSource).toContain("grid-template-rows: auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain("overflow: auto");
    expect(stylesSource).toContain("min-height: 420px");
  });

  it("keeps Agent empty states compact and left-aligned for dense workbench scanning", () => {
    expect(styles.emptyState).toBeTruthy();
    expect(routeSource).toContain("styles.emptyState");
    expect(stylesSource).toContain("place-items: start");
    expect(stylesSource).toContain("min-height: 72px");
    expect(stylesSource).toContain("text-align: left");
  });

  it("renders every Agent as a person name plus colored functional role tag", () => {
    expect(routeSource).toContain("agentDisplayInfo(agent, lang)");
    expect(routeSource).toContain("styles.agentRoleTag");
    expect(routeSource).toContain("agentRoleTag_${display.tone}");
    expect(routeSource).toContain("display.functionLabel");
  });

  it("supports bulk Agent selection with prompt editing and protected safe archive", () => {
    expect(routeSource).toContain("selectedBulkAgentIds");
    expect(routeSource).toContain("bulkApplyPromptTemplate");
    expect(routeSource).toContain("bulkArchiveAgents");
    expect(routeSource).toContain("bulkPurgeAgents");
    expect(routeSource).toContain("agentArchiveProtected(agent)");
    expect(routeSource).toContain("copy.bulkSkippedProtected");
    expect(routeSource).toContain("copy.bulkPurgeConfirm");
    expect(routeSource).toContain("copy.bulkPurgeResult");
    expect(routeSource).toContain("body: JSON.stringify({ promptTemplateId: bulkPromptTemplateId })");
    expect(routeSource).toContain('"/api/agents/bulk-archive"');
    expect(routeSource).toContain('"/api/agents/bulk-purge"');
    expect(routeSource).toContain("bulkPurgeWorkspaceCache");
    expect(routeSource).not.toContain("const archivedAgent = await fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agent.agentId)}`");
    expect(routeSource).not.toContain("for (const agent of selectedBulkAgents) {\n      if (agentArchiveProtected(agent))");
    expect(routeSource).not.toContain("`/api/agents/${encodeURIComponent(agent.agentId)}/purge`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("onClick={bulkPurgeAgents}");
    expect(routeSource).toContain("styles.bulkActionBar");
    expect(routeSource).toContain("styles.agentRowShell");
    expect(stylesSource).toContain("grid-template-rows: auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain("grid-template-columns: auto auto auto minmax(140px, 1fr)");
    expect(stylesSource).toContain("min-height: 26px");
  });
});
