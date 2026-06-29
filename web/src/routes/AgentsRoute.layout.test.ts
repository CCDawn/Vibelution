import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
import routeSource from "./AgentsRoute.tsx?raw";
import agentManagementNavSource from "./AgentManagementNav.tsx?raw";
import agentWorkspaceCacheSource from "./agentWorkspaceCache.ts?raw";
import styles from "./AgentsRoute.module.css";
import routerSource from "../app/router.tsx?raw";
import shellSource from "../app/AppShell.tsx?raw";

const stylesSource = readFileSync(new URL("./AgentsRoute.module.css", import.meta.url), "utf-8");

describe("AgentsRoute layout contract", () => {
  it("loads the read-only Agent config workspace endpoint", () => {
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspaceWithTeamIndexes>(\"/api/agents/config-workspace?includeRuntime=false\")");
    expect(routeSource).toContain("fetchJson<AgentConfigWorkspaceAgent[]>(\"/api/agents?includeArchived=true&detail=summary\")");
    expect(routeSource).toContain("queryKeys.agentSummary(true)");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(routeSource).toContain("const workspace = workspaceQuery.data ?? lightweightWorkspace");
    expect(routeSource).toContain('const fullWorkspaceNeeded = Boolean(createOpen || activePane === "config" || activePane === "activity" || requestedAgentId)');
    expect(routeSource).toContain("enabled: fullWorkspaceNeeded");
    expect(routeSource).toContain("staleTime: 10_000");
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
      routeSource.indexOf("<AgentPageHeader"),
    );
    expect(routeSource.indexOf('<AgentManagementNav active="agents" className={styles.managementNav} />')).toBeLessThan(
      routeSource.indexOf("<AgentSummaryStrip"),
    );
  });

  it("uses VUI product components for the Agent management header and summary strip", () => {
    expect(routeSource).toContain("AgentPageHeader");
    expect(routeSource).toContain("AgentSummaryStrip");
    expect(routeSource).toContain("agentSummaryMetrics");
    expect(routeSource).not.toContain("styles.summaryCard");
    expect(routeSource).not.toContain("styles.refreshButton");
    expect(routeSource).not.toContain(['import { Button } from "', "@hero", "ui/react", '"'].join(""));
    expect(routeSource).not.toContain("disabled: workspaceQuery.isFetching");
  });

  it("uses the VUI product panel surface for the Agent workspace columns", () => {
    expect(routeSource).toContain("AgentWorkspacePanel");
    expect(routeSource).toContain('as="aside" ariaLabel={copy.agentFilters}');
    expect(routeSource).toContain('as="main"');
    expect(routeSource).toContain("ariaLabel={activeGroupLabel}");
    expect(routeSource).toContain("ariaLabel={selectedAgent ? agentLabel(selectedAgent) : copy.title}");
    expect(stylesSource).not.toContain("0 14px 34px");
  });

  it("opens deep-linked Agent configuration and offers a governed return action", () => {
    expect(routeSource).toContain("useSearchParams");
    expect(routeSource).toContain("normalizeAgentConfigPane(searchParams.get(\"pane\"))");
    expect(routeSource).toContain("safeAgentCenterReturnTo(searchParams.get(\"returnTo\"))");
    expect(routeSource).toContain("agentCenterReturnLabel(searchParams.get(\"returnLabel\"), lang)");
    expect(routeSource).toContain('normalized === "config" || normalized === "activity" || normalized === "overview"');
    expect(routeSource).toContain("safeReturnToPath");
    expect(routeSource).toContain("return safeReturnToPath(value)");
    expect(routeSource).toContain("const routeTargetKey = requestedAgentId ? `${requestedAgentId}:${requestedPane}` : \"\"");
    expect(routeSource).toContain("workspace.agents.find((agent) => agent.agentId === requestedAgentId)");
    expect(routeSource).toContain("setSelectedAgentId(targetAgent.agentId)");
    expect(routeSource).toContain("setActivePane(requestedPane)");
    expect(routeSource).toContain('setActiveFilter(targetAgent.status === "archived" ? "archived" : "active")');
    expect(routeSource).toContain('normalized === "supervised_evolution"');
    expect(routeSource).toContain("返回监督进化");
    expect(routeSource).toContain('normalized === "tools"');
    expect(routeSource).toContain("返回工具配置");
    expect(routeSource).toContain('normalized === "teams"');
    expect(routeSource).toContain("返回团队");
    expect(routeSource).toContain('normalized === "chat"');
    expect(routeSource).toContain("返回会话");
    expect(routeSource).toContain('normalized === "memory"');
    expect(routeSource).toContain("返回记忆库");
    expect(routeSource).toContain('normalized === "research_flow"');
    expect(routeSource).toContain("返回科研流程画布");
    expect(routeSource).toContain("returnBannerTitle: \"返回跳转前页面\"");
    expect(routeSource).toContain("className={styles.returnBanner}");
    expect(routeSource).toContain("className={styles.returnBannerButton}");
    expect(routeSource).toContain("onClick={() => navigate(returnToPath)}");
    expect(routeSource).toContain("if (requestedAgentId && selectedAgent?.agentId === requestedAgentId)");
    expect(routeSource).not.toContain("className={styles.returnButton}");
    expect(styles.returnBanner).toBeTruthy();
    expect(styles.returnBannerCopy).toBeTruthy();
    expect(styles.returnBannerButton).toBeTruthy();
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

  it("keeps common Agent filters prominent and folds low-frequency filters away", () => {
    expect(routeSource).toContain('useState<FilterId>("active")');
    expect(routeSource).toContain("groupedFilters");
    expect(routeSource).toContain("advancedGroupedFilters");
    expect(routeSource).toContain("teamIndexes");
    expect(routeSource).toContain("copy.filterSections");
    expect(routeSource).toContain("copy.groupLabels");
    expect(routeSource).toContain('const sectionOrder = ["status", "boundary", "team_index"] as const;');
    expect(routeSource).toContain('const sectionOrder = ["source_scope", "mode", "reference"] as const;');
    expect(routeSource).toContain("workspaceTeamIndexes(workspace)");
    expect(routeSource).toContain('section === "team_index"');
    expect(routeSource).toContain('section === "source_scope"');
    expect(routeSource).toContain('team_index: "团队索引"');
    expect(routeSource).toContain('source_scope: "来源范围"');
    expect(routeSource).toContain('team_index: "Team indexes"');
    expect(routeSource).toContain('source_scope: "Source scope"');
    expect(routeSource).toContain('moreFilters: "更多筛选"');
    expect(routeSource).toContain('moreFilters: "More filters"');
    expect(agentWorkspaceCacheSource).toContain("sourceScopeGroupId");
    expect(agentWorkspaceCacheSource).toContain("teamIndexesWithoutAgentIds");
    expect(routeSource).toContain('section === "boundary"');
    expect(routeSource).toContain("managementSection,");
    expect(routeSource).toContain("styles.advancedFilterSection");
    expect(routeSource).toContain("styles.advancedFilterSummary");
    expect(routeSource).toContain("styles.advancedFilterBody");
    expect(routeSource).toContain("styles.groupSection");
    expect(routeSource).toContain("styles.groupSectionTitle");
    expect(routeSource).toContain("groupDisplayLabel(group, copy)");
    expect(styles.advancedFilterSection).toBeTruthy();
    expect(styles.advancedFilterSummary).toBeTruthy();
    expect(styles.advancedFilterBody).toBeTruthy();
    expect(styles.groupSection).toBeTruthy();
    expect(styles.groupSectionTitle).toBeTruthy();
  });

  it("keeps archived Agents out of lightweight mode filter counts", () => {
    expect(routeSource).toContain('lightweightAgentGroup("active", "可用 Agent", "status"');
    expect(routeSource).toContain('lightweightAgentGroup("archived", "已归档", "status"');
    expect(routeSource).toContain('lightweightAgentGroup("chat", "会话模式", "mode", "属于 Chat 运行模式或会话可用池的 Agent。", activeAgents');
    expect(routeSource).toContain('lightweightAgentGroup("research", "科研模式", "mode", "属于 Research 运行模式或科研池的 Agent。", activeAgents');
    expect(routeSource).toContain('lightweightAgentGroup("self_evolution", "自进化模式", "mode", "占用自进化模式引用的 Agent。", activeAgents');
  });

  it("labels Agent filter health counts instead of concatenating bare numbers", () => {
    expect(routeSource).toContain("function groupAriaLabel");
    expect(routeSource).toContain("aria-label={groupAriaLabel(displayLabel, group, copy, lang)}");
    expect(routeSource).toContain('group.id === "setup:inbox" ? copy.statusReminderShort : copy.healthIssueShort');
    expect(routeSource).not.toContain("{group.healthCount ? <em>{group.healthCount}</em> : null}");
  });

  it("localizes the workspace health badge and names the avatar editor trigger", () => {
    expect(routeSource).toContain("workspaceHealthStatusLabel(healthStatus, lang)");
    expect(routeSource).toContain("workspaceHealthStatusDescription(healthStatus, summary, lang)");
    expect(routeSource).toContain("copy.workspaceHealthStatus");
    expect(routeSource).toContain("detail: `${copy.workspaceHealthStatus}: ${healthStatusLabel}. ${healthStatusDescription}`");
    expect(routeSource).toContain("status={{");
    expect(routeSource).toContain("label: healthStatusLabel");
    expect(routeSource).toContain("title: healthStatusDescription");
    expect(routeSource).toContain("ariaLabel: `${copy.workspaceHealthStatus}: ${healthStatusLabel}. ${healthStatusDescription}`");
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

  it("lets each Agent inherit or override its context compression policy", () => {
    expect(routeSource).toContain("AgentContextCompressionPolicy");
    expect(routeSource).toContain("contextCompressionPolicy: AgentContextCompressionPolicyDraft");
    expect(routeSource).toContain("function contextCompressionDraftFromAgent");
    expect(routeSource).toContain("function contextCompressionPolicyFromDraft");
    expect(routeSource).toContain("contextCompressionPolicy: contextCompressionPolicyFromDraft(payload.draft.contextCompressionPolicy)");
    expect(routeSource).toContain("updateContextCompressionDraft");
    expect(routeSource).toContain("copy.contextCompressionPolicy");
    expect(routeSource).toContain("copy.contextCompressionInherit");
    expect(routeSource).toContain("copy.contextCompressionCustom");
    expect(routeSource).toContain("contextCompressionPolicyLine");
    expect(routeSource).toContain("compressionTriggerTokenLimit");
    expect(routeSource).toContain("modelContextWindowLimit");
    expect(routeSource).toContain("styles.compressionPolicyGrid");
    expect(routeSource).toContain("styles.compressionPolicySubgrid");
    expect(routeSource).toContain("styles.compressionPolicyFooter");
    expect(styles.compressionPolicyGrid).toBeTruthy();
    expect(styles.compressionPolicySubgrid).toBeTruthy();
    expect(styles.compressionPolicyFooter).toBeTruthy();
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

  it("shows GPT reasoning effort only for Agent slots whose bound model supports it", () => {
    expect(routeSource).toContain("reasoningEffortBySlot: Record<string, string>");
    expect(routeSource).toContain("agentModelSupportsReasoningEffort");
    expect(routeSource).toContain("supportsReasoningEffort");
    expect(routeSource).toContain("metadata.llmReasoningEffort = pruned");
    expect(routeSource).toContain("pruneAgentReasoningEffortBySlot");
    expect(routeSource).toContain("copy.reasoningEffort");
    expect(routeSource).toContain('value={normalizeAgentReasoningEffort(configDraft.reasoningEffortBySlot[slot.slot])}');
    expect(routeSource).toContain("<option value=\"high\">{copy.reasoningEffort}: {copy.reasoningEffortHigh}</option>");
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
    expect(routeSource).toContain("function hasActionableHealthIssue(agent: AgentConfigWorkspaceAgent | null | undefined)");
    expect(routeSource).toContain('issue.severity === "blocking" || issue.severity === "warning"');
    expect(routeSource).toContain("count(hasActionableHealthIssue)");
  });

  it("creates Agents through tool bundle presets instead of raw tool strings", () => {
    expect(routeSource).toContain("DEFAULT_SESSION_AGENT_ALLOWED_TOOLS");
    expect(routeSource).toContain("DEFAULT_SESSION_AGENT_PREFERRED_TOOLS");
    expect(routeSource).toContain("\"conversation_log_inspect_tool\"");
    expect(routeSource).not.toContain("\"read_file_tool\",");
    expect(routeSource).toContain("\"grep_search_tool\"");
    expect(routeSource).toContain("\"glob_tool\"");
    expect(routeSource).not.toContain("\"cli_agent_run_tool\"");
    expect(routeSource).not.toContain("\"image2_generate_tool\"");
    expect(routeSource).toContain("allowedTools: DEFAULT_SESSION_AGENT_ALLOWED_TOOLS.join(\", \")");
    expect(routeSource).toContain("const fallbackAllowedTools = toolBundles.length ? [] : expertiseFromDraft(draft.allowedTools)");
    expect(routeSource).toContain("const allowedTools = sortedIds(selectedAllowedTools)");
    expect(routeSource).toContain("const selectedPreferredTools = selectedToolPolicy.preferredTools.length");
    expect(routeSource).toContain("const preferredTools = sortedIds(selectedPreferredTools.filter((tool) => allowedTools.includes(tool)))");
    expect(routeSource).not.toContain("const sessionDefaultAllowedTools = workSession ? DEFAULT_SESSION_AGENT_ALLOWED_TOOLS : []");
    expect(routeSource).not.toContain("const sessionDefaultPreferredTools = workSession ? DEFAULT_SESSION_AGENT_PREFERRED_TOOLS : []");
    expect(routeSource).not.toContain("const allowedTools = sortedIds([...sessionDefaultAllowedTools, ...selectedAllowedTools])");
    expect(routeSource).toContain("selectedToolBundleIds: string[]");
    expect(routeSource).toContain("function defaultCreateToolBundleIds");
    expect(routeSource).toContain('const preferred = workSession ? ["core"] : ["core", "research", "collaboration"]');
    expect(routeSource).toContain("return bundles[0]?.bundleId ? [bundles[0].bundleId] : []");
    expect(routeSource).toContain("const hasToolPolicyChoice = selectedPolicy.selectedBundles.length > 0 || fallbackAllowedTools.length > 0");
    expect(routeSource).toContain("&& (workSession ? hasToolPolicyChoice : configuredToolCount > 0)");
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

  it("keeps disabled tool-query fallbacks referentially stable so Agent navigation can settle", () => {
    expect(routeSource).toContain("const EMPTY_TOOL_BUNDLES: ToolBundle[] = []");
    expect(routeSource).toContain("const EMPTY_TOOL_REGISTRY_ITEMS: ToolRegistryItem[] = []");
    expect(routeSource).toContain("const EMPTY_AGENT_CONFIG_GROUPS: AgentConfigWorkspaceGroup[] = []");
    expect(routeSource).toContain("const toolBundles = toolsQuery.data?.toolBundles ?? EMPTY_TOOL_BUNDLES");
    expect(routeSource).toContain("const tools = toolsQuery.data?.tools ?? EMPTY_TOOL_REGISTRY_ITEMS");
    expect(routeSource).toContain("const groups = workspace?.groups ?? EMPTY_AGENT_CONFIG_GROUPS");
    expect(routeSource).not.toContain("const toolBundles = toolsQuery.data?.toolBundles ?? []");
    expect(routeSource).not.toContain("const tools = toolsQuery.data?.tools ?? []");
    expect(routeSource).not.toContain("const groups = workspace?.groups ?? []");
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
    expect(routeSource).toContain("copy.toolPolicyPickerHint");
    expect(routeSource).toContain("copy.memoryPolicyPickerHint");
    expect(routeSource).not.toContain("copy.configGuideTitle");
    expect(routeSource).not.toContain("copy.configGuideBoundaryHint");
    expect(routeSource).not.toContain("styles.configGuidePanel");
    expect(routeSource).not.toContain("这页先回答三个问题");
    expect(routeSource).toContain("title={copy.llmSlotsHint}");
    expect(routeSource).toContain("title={copy.memoryPolicyPickerHint}");
    expect(routeSource).toContain("displayName: payload.draft.displayName");
    expect(routeSource).toContain("llmBindings: normalizeAgentLlmBindings(payload.draft.llmBindings)");
    expect(routeSource).toContain("promptTemplateId: payload.draft.promptTemplateId");
    expect(routeSource).toContain("toolPolicyId: payload.draft.toolPolicyId");
    expect(routeSource).toContain("memoryPolicyId: payload.draft.memoryPolicyId");
    expect(routeSource).toContain("status: payload.draft.status");
    expect(routeSource).toContain("method: \"PATCH\"");
    expect(routeSource).toContain("queryKeys.agentConfigWorkspace()");
    expect(styles.healthGuidePanel).toBeTruthy();
  });

  it("keeps Agent Center helper copy in hover text instead of permanent explanatory blocks", () => {
    expect(routeSource).toContain("<div title={copy.subtitle}>");
    expect(routeSource).not.toContain("<p className={styles.subtitle}>{copy.subtitle}</p>");
    expect(routeSource).toContain("<span className={styles.healthCell} title={issueSummary(agent.health, lang)}>");
    expect(routeSource).not.toContain("<small>{issueSummary(agent.health, lang)}</small>");
    expect(routeSource).toContain("<div title={column.description}>");
    expect(routeSource).not.toContain("<span>{column.description}</span>");
    expect(routeSource).toContain("title={createToolBundleSummaryValue.meta || copy.createAgentToolBundleEmpty}");
    expect(routeSource).not.toContain("<small>{createToolBundleSummaryValue.meta || copy.createAgentToolBundleEmpty}</small>");
    expect(routeSource).not.toContain("<small>{toolBundleMeta(bundle, lang)}</small>");
    expect(routeSource).toContain("<span className={styles.detailHealthStatus} title={issueSummary(selectedAgent.health, lang)}>");
    expect(routeSource).not.toContain("<small>{issueSummary(selectedAgent.health, lang)}</small>");
    expect(routeSource).toContain("title={`${slot.required ? copy.requiredSlot : copy.optionalSlot} · ${slot.description}`}");
    expect(routeSource).not.toContain("<small>{slot.required ? copy.requiredSlot : copy.optionalSlot}</small>");
    expect(routeSource).toContain("title={[toolPolicySourceLine, toolPolicySource?.description || copy.toolPolicyPickerHint].filter(Boolean).join(\"\\n\")}");
    expect(routeSource).not.toContain("<small>{toolPolicySourceLine}</small>");
    expect(routeSource).toContain("title={copy.createAgentHint}");
    expect(routeSource).toContain("title={copy.createAgentToolBundlesHint}");
    expect(routeSource).toContain("title={copy.returnBannerHint}");
    expect(routeSource).toContain("title={copy.avatarEditorHint}");
    expect(routeSource).toContain("title={copy.routeHint}");
    expect(routeSource).toContain("title={copy.managementBriefHint}");
    expect(routeSource).toContain("title={copy.personaHint}");
    expect(routeSource).toContain("title={copy.taskHint}");
    expect(routeSource).toContain("title={copy.maintenanceHint}");
    expect(routeSource).toContain("title={copy.resetAgentHint}");
    expect(routeSource).not.toContain("<p>{copy.createAgentHint}</p>");
    expect(routeSource).not.toContain("<span>{copy.returnBannerHint}</span>");
    expect(routeSource).not.toContain("<p>{copy.avatarEditorHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.routeHint}</p>");
    expect(routeSource).not.toContain("<p className={styles.contextLine}>{copy.personaHint}</p>");
    expect(routeSource).not.toContain("<p className={styles.contextLine}>{copy.taskHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.maintenanceHint}</p>");
    expect(routeSource).not.toContain("<p>{copy.resetAgentHint}</p>");
    expect(stylesSource).not.toContain(".subtitle");
    expect(stylesSource).not.toContain(".healthCell small");
    expect(stylesSource).not.toContain(".detailHealthStatus small");
    expect(stylesSource).not.toContain(".createToolBundleOption small");
    expect(stylesSource).not.toContain(".llmSlotField span small");
  });

  it("explains Agent health states with reason and next action instead of a bare hint pill", () => {
    expect(routeSource).toContain('return lang === "zh" ? "提醒" : "Notice"');
    expect(routeSource).toContain("function issueSummary");
    expect(routeSource).toContain("function issueNextStep");
    expect(routeSource).toContain("function issuePanelLabel");
    expect(routeSource).toContain("function issueDisplayTitle");
    expect(routeSource).toContain("Inbox 有待处理消息");
    expect(routeSource).toContain("这是 Inbox 待办提醒，不代表配置坏了");
    expect(routeSource).toContain("styles.healthCell");
    expect(routeSource).toContain("styles.detailHealthStatus");
    expect(routeSource).toContain("copy.healthNextStep");
    expect(routeSource).toContain("copy.statusReminders");
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
    expect(routeSource).toContain("compactProjectionRoute(room");
    expect(routeSource).toContain("`/chat?room=${encodeURIComponent(room.roomId)}`");
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
    expect(routeSource).toContain("reference.projectionEdit?.canonicalEditRoute || reference.sourceRef?.canonicalEditRoute");
    expect(routeSource).toContain("compactProjectionRoute(room");
    expect(routeSource).toContain('`/teams?team=${encodeURIComponent(reference.sourceId)}`');
    expect(routeSource).toContain("styles.referenceRouteButton");
    expect(routeSource).toContain("styles.referenceStatusStale");
  });

  it("routes detailed Agent tool permissions to the Tools page", () => {
    expect(routeSource).toContain("agentCenterToolsRoute");
    expect(routeSource).toContain("const selectedAgentReturnRoute = selectedAgent?.agentId");
    expect(routeSource).toContain("const selectedAgentToolConfigRoute = useMemo(");
    expect(routeSource).toContain('returnLabel: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(routeSource).toContain("copy.toolPolicyTitle");
    expect(routeSource).toContain("toolPolicySourceLine");
    expect(routeSource).toContain("toolPolicySource?.description");
    expect(routeSource).toContain("工具能力已迁移到 Agent 管理的工具页集中配置");
    expect(routeSource).toContain("配置工具能力");
    expect(routeSource).toContain("去工具页配置");
    expect(routeSource).toContain("onClick={() => navigate(selectedAgentToolConfigRoute)}");
    expect(routeSource).toContain("copy.toolCategoryCount");
  });

  it("routes Agent prompt configuration to the Prompt Center", () => {
    expect(routeSource).toContain("agentCenterPromptsRoute");
    expect(routeSource).toContain("const selectedAgentPromptConfigRoute = useMemo(");
    expect(routeSource).toContain("templateId: configDraft.promptTemplateId || selectedAgent.promptTemplateId");
    expect(routeSource).toContain('focus: "editor"');
    expect(routeSource).toContain('returnLabel: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(routeSource).toContain("styles.promptConfigRow");
    expect(routeSource).toContain("onClick={() => navigate(selectedAgentPromptConfigRoute)}");
    expect(routeSource).toContain("配置提示词");
  });

  it("adds cross-center links for model, context, and memory configuration", () => {
    expect(routeSource).toContain("agentCenterModelsRoute");
    expect(routeSource).toContain("agentCenterMemoryRoute");
    expect(routeSource).toContain("const selectedAgentModelConfigRoute = useMemo(");
    expect(routeSource).toContain("const selectedAgentContextConfigRoute = useMemo(");
    expect(routeSource).toContain("const selectedAgentMemoryConfigRoute = useMemo(");
    expect(routeSource).toContain('section: "models-profiles"');
    expect(routeSource).toContain('section: "runtime-context"');
    expect(routeSource).toContain('view: "agents"');
    expect(routeSource).toContain("returnTo: selectedAgentReturnRoute");
    expect(routeSource).toContain("styles.configDeepLinkRow");
    expect(routeSource).toContain("onClick={() => navigate(selectedAgentModelConfigRoute)}");
    expect(routeSource).toContain("onClick={() => navigate(selectedAgentContextConfigRoute)}");
    expect(routeSource).toContain("onClick={() => navigate(selectedAgentMemoryConfigRoute)}");
    expect(routeSource).toContain("去模型库配置");
    expect(routeSource).toContain("去上下文配置");
    expect(routeSource).toContain("去记忆页配置");
    expect(styles.configDeepLinkRow).toBeTruthy();
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
    expect(routeSource).toContain("const sectionOrder = [\"status\", \"boundary\", \"team_index\"] as const");
    expect(routeSource).toContain("const sectionOrder = [\"source_scope\", \"mode\", \"reference\"] as const");
    expect(routeSource).toContain("copy.managementModelPrompt");
    expect(routeSource).toContain("copy.managementWorkspace");
    expect(routeSource).toContain("copy.nextSetupModelPrompt");
    expect(routeSource).toContain("copy.nextSetupWorkspace");
    expect(routeSource).toContain("Model / instructions");
    expect(routeSource).toContain("Check workspace boundary");
    expect(routeSource).toContain("配置模型与项目指令");
    expect(routeSource).toContain("检查工作区边界");
    expect(routeSource).toContain("Session entry Agents");
    expect(routeSource).toContain("Team / research role Agents");
    expect(routeSource).toContain("会话入口 Agent");
    expect(routeSource).toContain("团队/科研角色 Agent");
    expect(routeSource).toContain("function buildVisibleAgentColumns");
    expect(routeSource).toContain("teamIndexGroups: AgentTeamIndexGroup[]");
    expect(routeSource).toContain("group.section === \"team_index\"");
    expect(routeSource).toContain("id: `team_agents:${group.id}`");
    expect(routeSource).toContain("unassignedNonSessionAgents");
    expect(routeSource).toContain("copy.nonSessionAgentColumn");
    expect(routeSource).toContain("nonSessionAgents = agents.filter((agent) => !isWorkSessionAgent(agent))");
    expect(routeSource).toContain("buildVisibleAgentColumns(visibleAgents, copy, teamIndexGroups)");
    expect(routeSource).toContain("styles.agentColumnGrid");
    expect(routeSource).toContain("styles.agentColumnHeader");
    expect(routeSource).toContain("非会话 Agent");
    expect(routeSource).toContain("Non-session Agents");
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

  it("optimistically removes single-Agent archive and purge actions before backend confirmation", () => {
    expect(routeSource).toContain("function optimisticArchivedAgent(agent: AgentConfigWorkspaceAgent)");
    expect(routeSource).toContain("queryClient.cancelQueries({ queryKey: queryKeys.agentConfigWorkspace() })");
    expect(routeSource).toContain("const previousSelectedAgentId = selectedAgentId");
    expect(routeSource).toContain("const previousActivePane = activePane");
    expect(routeSource).toContain("archivedWorkspaceCache(current, optimisticArchivedAgent(optimisticAgent))");
    expect(routeSource).toContain("purgedWorkspaceCache(current, payload.agentId)");
    expect(routeSource).toContain("return { previousWorkspace, previousSelectedAgentId, previousActivePane }");
    expect(routeSource).toContain("queryClient.setQueryData(queryKeys.agentConfigWorkspace(), context.previousWorkspace)");
    expect(routeSource).toContain("setSelectedAgentId(context?.previousSelectedAgentId ?? \"\")");
    expect(routeSource).toContain("setActivePane(context?.previousActivePane ?? \"overview\")");
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

  it("reconciles stale direct-session caches after resetting an Agent session", () => {
    expect(routeSource).toContain("type AgentResetSummary");
    expect(routeSource).toContain("function reconcileResetDirectSession");
    expect(routeSource).toContain("previousDirectSessionId");
    expect(routeSource).toContain("replacementDirectSessionId");
    expect(routeSource).toContain("reconcileResetDirectSession(result.resetSummary)");
    expect(routeSource).toContain("queryClient.removeQueries({ queryKey: queryKeys.session(previousDirectSessionId), exact: true })");
    expect(routeSource).toContain("chatWorkspaceCache.afterChatWorkspaceReset()");
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
    expect(stylesSource).toContain("grid-auto-rows: minmax(180px, auto)");
    expect(stylesSource).toContain("grid-template-rows: auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain("overflow: auto");
    expect(stylesSource).toContain("min-height: 220px");
  });

  it("keeps the 1024px Agent management stack compact enough to show list and detail context", () => {
    const narrowBreakpoint = stylesSource.slice(stylesSource.indexOf("@media (max-width: 860px)"));

    expect(narrowBreakpoint).toContain("grid-auto-rows: auto");
    expect(narrowBreakpoint).toContain("align-content: start");
    expect(narrowBreakpoint).toContain(".filterPanel {\n    min-height: 150px;");
    expect(narrowBreakpoint).toContain(".agentPanel {\n    min-height: 240px;");
    expect(narrowBreakpoint).toContain(".detailPanel {\n    min-height: 180px;");
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
    expect(routeSource).toContain("bulkSelectionAnchorAgentId");
    expect(routeSource).toContain("event.ctrlKey || event.metaKey || event.shiftKey");
    expect(routeSource).toContain("visibleAgents.slice(start, end + 1)");
    expect(routeSource).toContain("bulkConfigDraftFromAgents");
    expect(routeSource).toContain("bulkApplyAgentConfig");
    expect(routeSource).toContain("bulkApplyPromptTemplate");
    expect(routeSource).toContain("bulkArchiveAgents");
    expect(routeSource).toContain("bulkPurgeAgents");
    expect(routeSource).toContain("agentArchiveProtected(agent)");
    expect(routeSource).toContain('metadataFlag(agent, "fixedRole")');
    expect(routeSource).toContain('metadataString(agent, "supervisedRole")');
    expect(routeSource).toContain("copy.bulkSkippedProtected");
    expect(routeSource).toContain("copy.bulkPurgeConfirm");
    expect(routeSource).toContain("copy.bulkPurgeResult");
    expect(routeSource).toContain("copy.bulkEditMixed");
    expect(routeSource).toContain('"/api/agents/bulk-prompt-template"');
    expect(routeSource).toContain('"/api/agents/bulk-config"');
    expect(routeSource).toContain("applyFields: bulkConfigApplyFields(bulkConfigApply)");
    expect(routeSource).toContain("patch: bulkConfigPatchFromDraft(bulkConfigDraft, bulkConfigApply)");
    expect(routeSource).toContain("body: JSON.stringify({ agentIds: selectedBulkAgents.map((agent) => agent.agentId), promptTemplateId: bulkPromptTemplateId })");
    expect(routeSource).toContain("bulkUpdatedAgentWorkspaceCache");
    expect(routeSource).toContain('"/api/agents/bulk-archive"');
    expect(routeSource).toContain('"/api/agents/bulk-purge"');
    expect(routeSource).toContain("bulkPurgeWorkspaceCache");
    expect(routeSource).not.toContain("const archivedAgent = await fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agent.agentId)}`");
    expect(routeSource).not.toContain("const updatedAgent = await fetchJson<AgentConfigWorkspaceAgent>(`/api/agents/${encodeURIComponent(agent.agentId)}`");
    expect(routeSource).not.toContain("for (const agent of selectedBulkAgents) {\n      if (agentArchiveProtected(agent))");
    expect(routeSource).not.toContain("`/api/agents/${encodeURIComponent(agent.agentId)}/purge`");
    expect(routeSource).toContain('method: "DELETE"');
    expect(routeSource).toContain("onClick={bulkPurgeAgents}");
    expect(routeSource).toContain("onClick={bulkApplyAgentConfig}");
    expect(routeSource).toContain("styles.bulkActionBar");
    expect(routeSource).toContain("styles.bulkSelectionList");
    expect(routeSource).toContain("styles.bulkFieldHeader");
    expect(routeSource).toContain("styles.agentRowBulkSelected");
    expect(routeSource).toContain("styles.agentRowShell");
    expect(stylesSource).toContain("grid-template-rows: auto auto minmax(0, 1fr)");
    expect(stylesSource).toContain(".bulkActionBar {\n  display: flex;");
    expect(stylesSource).toContain("flex-wrap: wrap");
    expect(stylesSource).toContain("flex: 1 1 220px");
    expect(stylesSource).toContain(".bulkPromptPicker span");
    expect(stylesSource).toContain("white-space: nowrap");
    expect(stylesSource).toContain("min-height: 26px");
    expect(stylesSource).toContain(".agentRowBulkSelected");
  });
});
