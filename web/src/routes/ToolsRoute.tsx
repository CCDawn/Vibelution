import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CheckSquare, CircleSlash, FlaskConical, Power, RefreshCw, Search, Square, Trash2, Wrench } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";
import { Link } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  GeneratedToolDeleteResponse,
  ToolDependencyHealth,
  ToolAgentScopeState,
  ToolAgentScopeSummary,
  ToolBundle,
  ToolImage2ModelConfig,
  ToolPolicy,
  ToolRegistryItem,
  ToolRegistryPayload,
  ToolTestResponse,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import type { TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import { clampPaneWidth, keyboardPaneWidth, storedPaneWidth } from "./resizablePane";
import styles from "./ToolsRoute.module.css";

type ToolFilter = "all" | "built_in" | "generated" | "llm" | "enabled";
type ToolPolicyMode = "inherited" | "explicit_required" | "allowed" | "blocked" | "excluded";
type ToolBundleGroup = {
  bundleId: string;
  label: string;
  description: string;
  tools: ToolRegistryItem[];
  highRiskToolCount: number;
  explicitAllowToolCount: number;
};
type ScopedToolTestResult = {
  key: string;
  result: ToolTestResponse;
};
type Translate = (key: TranslationKey) => string;

const FILTERS: ToolFilter[] = ["all", "built_in", "generated", "llm", "enabled"];
const TOOLS_LEFT_PANEL_WIDTH_KEY = "vibelution.tools.left-panel-width";
const TOOLS_LEFT_PANEL_BOUNDS = { min: 260, max: 520 };
const TOOLS_LEFT_PANEL_DEFAULT_WIDTH = 350;
const MAIN_AGENT_SCOPE_ID = "main_agent";
const IMAGE2_TOOL_NAME = "image2_generate_tool";
const WEB_SEARCH_TOOL_NAME = "web_search_tool";

function displaySource(source: string, lang: string) {
  if (source === "built_in") {
    return lang === "zh" ? "内置" : "Built-in";
  }
  if (source === "generated") {
    return lang === "zh" ? "生成" : "Generated";
  }
  return source;
}

function statusTone(tool: ToolRegistryItem) {
  if (tool.status === "invalid") {
    return "error";
  }
  if (tool.runtimeActive || tool.llmVisible) {
    return "active";
  }
  if (tool.enabled) {
    return "enabled";
  }
  return "idle";
}

function scopeStateForTool(tool: ToolRegistryItem, scopeId: string): ToolAgentScopeState {
  return (
    tool.agentScopes?.[scopeId] ?? {
      visible: true,
      callable: tool.runtimeActive,
      llmVisible: tool.llmVisible,
      runtimeActive: tool.runtimeActive,
      testable: tool.testPolicy.callable,
      blockReason: tool.blockReason || tool.validationError || "",
    }
  );
}

function schemaPreview(tool: ToolRegistryItem) {
  try {
    return JSON.stringify(tool.argsSchema ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function jsonPreview(value: unknown) {
  try {
    return JSON.stringify(value ?? {}, null, 2);
  } catch {
    return "{}";
  }
}

function testPolicyLabel(mode: string, lang: string) {
  if (mode === "safe_builtin_fixture") {
    return lang === "zh" ? "安全白名单真实调用" : "Safe allow-listed runtime call";
  }
  if (mode === "generated_manifest_simulation") {
    return lang === "zh" ? "Manifest 模拟调用" : "Manifest simulation";
  }
  if (mode === "blocked") {
    return lang === "zh" ? "安全策略阻塞" : "Blocked by safety policy";
  }
  return mode || (lang === "zh" ? "未知策略" : "Unknown policy");
}

function matchesFilter(tool: ToolRegistryItem, filter: ToolFilter) {
  if (filter === "all") {
    return true;
  }
  if (filter === "built_in" || filter === "generated") {
    return tool.source === filter;
  }
  if (filter === "llm") {
    return tool.llmVisible;
  }
  return tool.source === "generated" && tool.enabled;
}

function filterLabel(filter: ToolFilter, lang: string) {
  const zh = {
    all: "全部",
    built_in: "内置",
    generated: "生成",
    llm: "LLM 可见",
    enabled: "已启用",
  };
  const en = {
    all: "All",
    built_in: "Built-in",
    generated: "Generated",
    llm: "LLM-visible",
    enabled: "Enabled",
  };
  return (lang === "zh" ? zh : en)[filter];
}

function toolFilterCounts(tools: ToolRegistryItem[]) {
  return {
    all: tools.length,
    built_in: tools.filter((tool) => tool.source === "built_in").length,
    generated: tools.filter((tool) => tool.source === "generated").length,
    llm: tools.filter((tool) => tool.llmVisible).length,
    enabled: tools.filter((tool) => tool.source === "generated" && tool.enabled).length,
  } satisfies Record<ToolFilter, number>;
}

function unbundledToolGroupLabel(lang: string) {
  return lang === "zh" ? "未归入工具包" : "Unbundled tools";
}

function toolBundleGroups(tools: ToolRegistryItem[], bundles: ToolBundle[], lang: string): ToolBundleGroup[] {
  const toolByName = new Map(tools.map((tool) => [tool.name, tool]));
  const groupedToolNames = new Set<string>();
  const groups: ToolBundleGroup[] = [];
  for (const bundle of bundles) {
    const groupTools = bundle.toolNames.map((toolName) => toolByName.get(toolName)).filter((tool): tool is ToolRegistryItem => Boolean(tool));
    if (!groupTools.length) {
      continue;
    }
    groupTools.forEach((tool) => groupedToolNames.add(tool.name));
    groups.push({
      bundleId: bundle.bundleId,
      label: bundle.label,
      description: bundle.description,
      tools: groupTools,
      highRiskToolCount: groupTools.filter((tool) => tool.permissionTier === "high").length,
      explicitAllowToolCount: groupTools.filter((tool) => tool.permissionPolicy?.requiresExplicitAllow).length,
    });
  }
  const unbundledTools = tools.filter((tool) => !groupedToolNames.has(tool.name));
  if (unbundledTools.length) {
    groups.push({
      bundleId: "unbundled",
      label: unbundledToolGroupLabel(lang),
      description: lang === "zh" ? "这些工具暂未归入任何工具包，建议先确认用途和风险。" : "Tools not assigned to a package yet. Review purpose and risk before use.",
      tools: unbundledTools,
      highRiskToolCount: unbundledTools.filter((tool) => tool.permissionTier === "high").length,
      explicitAllowToolCount: unbundledTools.filter((tool) => tool.permissionPolicy?.requiresExplicitAllow).length,
    });
  }
  return groups;
}

function bundleLabelsForTool(tool: ToolRegistryItem, bundles: ToolBundle[], lang: string) {
  const labels = (tool.bundleIds ?? [])
    .map((bundleId) => bundles.find((bundle) => bundle.bundleId === bundleId)?.label ?? "")
    .filter(Boolean);
  return labels.length ? labels : [unbundledToolGroupLabel(lang)];
}

function readinessTone(ready: boolean) {
  return ready ? "ready" : "blocked";
}

function toolReadinessCards(tool: ToolRegistryItem, scopeState: ToolAgentScopeState, activeScope: ToolAgentScopeSummary, t: Translate) {
  return [
    {
      key: "scopeVisible",
      label: t("toolsScopeVisible"),
      value: scopeState.visible ? t("toolsVisibleToAgent") : t("toolsHiddenFromAgent"),
      ready: scopeState.visible,
    },
    {
      key: "scopeCallable",
      label: activeScope.isSubagent ? t("toolsSelectedAgent") : t("toolsRuntimeActive"),
      value: scopeState.callable ? t("toolsReady") : t("toolsScopeBlocked"),
      ready: scopeState.callable,
    },
    {
      key: "test",
      label: t("toolsTestPolicy"),
      value: scopeState.testable ? t("toolsTestable") : t("toolsBlocked"),
      ready: scopeState.testable,
    },
    {
      key: "delete",
      label: t("toolsDeleteAllowed"),
      value: tool.deleteAllowed ? t("toolsCanDelete") : t("toolsProtected"),
      ready: tool.deleteAllowed,
    },
  ];
}

function defaultToolPolicy(policyId = "default"): ToolPolicy {
  return {
    policyId,
    allowedTools: [],
    preferredTools: [],
    blockedTools: [],
    readScopes: [],
    writeScopes: [],
    allowedCommandKinds: [],
    blockedCommandPatterns: [],
    networkAccess: "inherit",
    mutationAccess: "inherit",
    maxCallsPerTurn: 0,
    perToolRules: {},
  };
}

function toolPolicyForAgent(agent: AgentInstance | null | undefined): ToolPolicy {
  return agent?.toolPolicy ?? defaultToolPolicy(agent?.toolPolicyId || "default");
}

function toolPolicyModeCounts(policy: ToolPolicy, tools: ToolRegistryItem[]) {
  return tools.reduce(
    (counts, tool) => {
      counts[toolPolicyMode(policy, tool)] += 1;
      return counts;
    },
    { inherited: 0, explicit_required: 0, allowed: 0, blocked: 0, excluded: 0 } satisfies Record<ToolPolicyMode, number>,
  );
}

function toolPolicyMode(policy: ToolPolicy, tool: ToolRegistryItem | string): ToolPolicyMode {
  const toolName = typeof tool === "string" ? tool : tool.name;
  const requiresExplicitAllow = typeof tool === "string" ? false : Boolean(tool.permissionPolicy?.requiresExplicitAllow);
  const allowed = new Set(policy.allowedTools ?? []);
  const blocked = new Set(policy.blockedTools ?? []);
  if (blocked.has(toolName)) {
    return "blocked";
  }
  if (allowed.has(toolName)) {
    return "allowed";
  }
  if (requiresExplicitAllow) {
    return "explicit_required";
  }
  if (allowed.size > 0) {
    return "excluded";
  }
  return "inherited";
}

function toolPolicyModeLabel(mode: ToolPolicyMode, lang: string) {
  const zh = {
    inherited: "跟随默认",
    explicit_required: "需显式授权",
    allowed: "允许清单",
    blocked: "禁用",
    excluded: "未在允许清单",
  };
  const en = {
    inherited: "Default",
    explicit_required: "Explicit allow required",
    allowed: "Allow-list",
    blocked: "Blocked",
    excluded: "Excluded",
  };
  return (lang === "zh" ? zh : en)[mode];
}

function agentTestLabel(agent: ToolTestResponse["agent"] | null | undefined, lang: string) {
  const agentId = String(agent?.agentId ?? "").trim();
  if (!agentId) {
    return lang === "zh" ? "未绑定 Agent" : "No Agent";
  }
  const code = String(agent?.agentCode ?? "").trim();
  const name = String(agent?.displayName ?? "").trim();
  return code && name ? `${code} · ${name}` : code || name || agentId;
}

function toolTestKey(toolId: string | null | undefined, agentScopeId: string | null | undefined, agentId: string | null | undefined) {
  return [toolId ?? "", agentScopeId ?? "", agentId ?? ""].join("::");
}

function testResultSummaryCards(result: ToolTestResponse, t: Translate) {
  return [
    {
      key: "status",
      label: t("toolsTestResult"),
      value: result.status,
      ok: result.status === "succeeded",
    },
    {
      key: "agent",
      label: t("toolsAgentCompatibility"),
      value: result.agentCompatibility.status,
      ok: result.agentCompatibility.status === "succeeded",
    },
    {
      key: "timeout",
      label: t("toolsTimedOut"),
      value: result.timeout.timedOut ? t("yes") : t("no"),
      ok: !result.timeout.timedOut,
    },
    {
      key: "duration",
      label: t("toolsDuration"),
      value: `${result.timeout.durationMs}ms`,
      ok: true,
    },
  ];
}

function image2ModelLabel(config: ToolImage2ModelConfig | undefined, lang: string) {
  const selected = config?.selectedModel;
  if (!selected) {
    return lang === "zh" ? "加载中" : "Loading";
  }
  if (!selected.modelRef) {
    return lang === "zh" ? "未设置，使用环境变量/内置回退" : "Not set, using env/built-in fallback";
  }
  return selected.label || selected.model || selected.modelRef;
}

function image2KeyStateLabel(config: ToolImage2ModelConfig | undefined, lang: string) {
  const selected = config?.selectedModel;
  if (!selected || !selected.modelRef) {
    return lang === "zh" ? "按回退配置解析" : "Resolved by fallback config";
  }
  if (!selected.apiKeyEnv) {
    return lang === "zh" ? "未声明密钥变量" : "No key env declared";
  }
  return selected.apiKeyConfigured
    ? lang === "zh" ? "密钥已配置" : "Key configured"
    : lang === "zh" ? "密钥未配置" : "Key missing";
}

function image2DiscoveryStateLabel(config: ToolImage2ModelConfig | undefined, lang: string) {
  const status = config?.selectedModel.modelDiscoveryStatus || "";
  const count = config?.selectedModel.discoveredModels?.length ?? 0;
  if (status === "succeeded") {
    return lang === "zh" ? `已发现 ${count} 个图片模型` : `${count} image models`;
  }
  if (status === "empty") {
    return lang === "zh" ? "未发现图片模型" : "No image models found";
  }
  if (status === "failed") {
    return lang === "zh" ? "发现失败" : "Discovery failed";
  }
  if (status === "skipped") {
    return lang === "zh" ? "无需发现" : "Discovery skipped";
  }
  return lang === "zh" ? "未请求发现" : "Discovery not requested";
}

function scopeLabel(scope: ToolAgentScopeSummary, lang: string, t: Translate) {
  if (scope.id === "main_agent") {
    return t("toolsMainAgent");
  }
  if (scope.id === "subagent_default") {
    return t("toolsSubagentDefault");
  }
  if (scope.id === "subagent_explorer") {
    return t("toolsSubagentExplorer");
  }
  if (scope.id === "subagent_worker") {
    return t("toolsSubagentWorker");
  }
  return scope.label || (lang === "zh" ? "Agent" : "Agent");
}

function toolsBulkCopy(lang: string) {
  return lang === "zh"
    ? {
        selected: "已选",
        selectVisible: "选择当前列表",
        clear: "清空",
        enable: "批量启用",
        disable: "批量停用",
        delete: "批量删除",
        working: "批量处理中...",
        noSelection: "请先选择工具。",
        skippedToggle: "不是可启停的已验证生成工具，跳过",
        skippedDelete: "受保护或不可删除，跳过",
        deleteConfirm: "确认批量删除已选工具？受保护或不可删除的工具会自动跳过。",
        enableResult: "批量启用完成",
        disableResult: "批量停用完成",
        deleteResult: "批量删除完成",
      }
    : {
        selected: "Selected",
        selectVisible: "Select visible",
        clear: "Clear",
        enable: "Bulk enable",
        disable: "Bulk disable",
        delete: "Bulk delete",
        working: "Working...",
        noSelection: "Select tools first.",
        skippedToggle: "Not a toggleable validated generated tool; skipped",
        skippedDelete: "Protected or not deletable; skipped",
        deleteConfirm: "Delete the selected tools? Protected or non-deletable tools will be skipped.",
        enableResult: "Bulk enable finished",
        disableResult: "Bulk disable finished",
        deleteResult: "Bulk delete finished",
      };
}

function toolsBulkActionSummary(action: string, success: number, skipped: number, failed: number, notes: string[], lang: string) {
  const parts = lang === "zh"
    ? [`成功 ${success}`, `跳过 ${skipped}`, `失败 ${failed}`]
    : [`success ${success}`, `skipped ${skipped}`, `failed ${failed}`];
  const preview = notes.slice(0, 3).join("；");
  return preview ? `${action}: ${parts.join(" / ")}。${preview}` : `${action}: ${parts.join(" / ")}`;
}

function canBulkToggleTool(tool: ToolRegistryItem) {
  return tool.source === "generated" && Boolean(tool.validated) && tool.status === "validated";
}

export function ToolsRoute() {
  const { lang, t } = useAppI18n();
  const bulkCopy = useMemo(() => toolsBulkCopy(lang), [lang]);
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<ToolFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [activeAgentScopeId, setActiveAgentScopeId] = useState(MAIN_AGENT_SCOPE_ID);
  const [activePolicyAgentId, setActivePolicyAgentId] = useState("");
  const [activeToolId, setActiveToolId] = useState<string | null>(null);
  const [leftPanelWidth, setLeftPanelWidth] = useState(() =>
    storedPaneWidth(TOOLS_LEFT_PANEL_WIDTH_KEY, TOOLS_LEFT_PANEL_DEFAULT_WIDTH, TOOLS_LEFT_PANEL_BOUNDS),
  );
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [selectedToolIds, setSelectedToolIds] = useState<Set<string>>(() => new Set());
  const [bulkToolPending, setBulkToolPending] = useState(false);
  const [notice, setNotice] = useState<{ tone: "neutral" | "success" | "error"; text: string }>({
    tone: "neutral",
    text: "",
  });
  const [testResult, setTestResult] = useState<ScopedToolTestResult | null>(null);
  const pageVisible = usePageVisibility();

  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    staleTime: 30_000,
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });

  const image2ModelsQuery = useQuery({
    queryKey: queryKeys.toolImage2Models(),
    queryFn: () => fetchJson<ToolImage2ModelConfig>("/api/tools/image2/models"),
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.tools() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.toolImage2Models() });
    void queryClient.invalidateQueries({ queryKey: queryKeys.toolWebSearchHealth() });
  };

  const tools = toolsQuery.data?.tools ?? [];
  const toolBundles = toolsQuery.data?.toolBundles ?? [];
  const agentScopes = toolsQuery.data?.agentScopes ?? [];
  const activeAgentScope =
    agentScopes.find((scope) => scope.id === activeAgentScopeId) ??
    ({
      id: MAIN_AGENT_SCOPE_ID,
      label: "Main agent",
      kind: "main",
      isSubagent: false,
      mode: "runtime",
      description: "",
      counts: { total: tools.length, visible: tools.length, callable: tools.length, blocked: 0 },
    } satisfies ToolAgentScopeSummary);
  const visibleTools = useMemo(() => {
    const query = searchText.trim().toLowerCase();
    return tools.filter((tool) => {
      const scopeState = scopeStateForTool(tool, activeAgentScopeId);
      if (!scopeState.visible) {
        return false;
      }
      if (!matchesFilter(tool, activeFilter)) {
        return false;
      }
      if (!query) {
        return true;
      }
      return [
        tool.name,
        tool.description,
        tool.source,
        tool.status,
        tool.category,
        tool.categoryLabel,
        ...(tool.bundleIds ?? []),
        ...bundleLabelsForTool(tool, toolBundles, lang),
      ].join(" ").toLowerCase().includes(query);
    });
  }, [activeAgentScopeId, activeFilter, lang, searchText, toolBundles, tools]);
  const visibleToolBundleGroups = useMemo(
    () => toolBundleGroups(visibleTools, toolBundles, lang),
    [lang, toolBundles, visibleTools],
  );
  const selectedTools = useMemo(
    () => visibleTools.filter((tool) => selectedToolIds.has(tool.id)),
    [selectedToolIds, visibleTools],
  );
  const allVisibleToolsSelected = visibleTools.length > 0 && selectedTools.length === visibleTools.length;
  const activeTool = tools.find((tool) => tool.id === activeToolId) ?? visibleTools[0] ?? null;
  const agentPolicyWorkspaceNeeded = Boolean(activeTool);
  const activeToolBundleLabels = activeTool ? bundleLabelsForTool(activeTool, toolBundles, lang) : [];
  const activeScopeState = activeTool ? scopeStateForTool(activeTool, activeAgentScope.id) : null;

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    enabled: agentPolicyWorkspaceNeeded,
    staleTime: 30_000,
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });
  const activeAgents = useMemo(
    () => (agentsQuery.data ?? []).filter((agent) => agent.status !== "archived"),
    [agentsQuery.data],
  );
  const activePolicyAgent = activeAgents.find((agent) => agent.agentId === activePolicyAgentId) ?? activeAgents[0] ?? null;
  const activePolicy = toolPolicyForAgent(activePolicyAgent);
  const activePolicyMode = activeTool && activePolicyAgent ? toolPolicyMode(activePolicy, activeTool) : "inherited";
  const policyModeCounts = useMemo(() => toolPolicyModeCounts(activePolicy, tools), [activePolicy, tools]);
  const scopedTools = useMemo(
    () => tools.filter((tool) => scopeStateForTool(tool, activeAgentScopeId).visible),
    [activeAgentScopeId, tools],
  );
  const filterCounts = useMemo(() => toolFilterCounts(scopedTools), [scopedTools]);

  useEffect(() => {
    if (!activeToolId || !tools.some((tool) => tool.id === activeToolId)) {
      setActiveToolId(visibleTools[0]?.id ?? null);
    }
  }, [activeToolId, tools, visibleTools]);

  useEffect(() => {
    if (!agentScopes.length || agentScopes.some((scope) => scope.id === activeAgentScopeId)) {
      return;
    }
    setActiveAgentScopeId(MAIN_AGENT_SCOPE_ID);
  }, [activeAgentScopeId, agentScopes]);

  useEffect(() => {
    if (!activeAgents.length) {
      setActivePolicyAgentId("");
      return;
    }
    if (!activePolicyAgentId || !activeAgents.some((agent) => agent.agentId === activePolicyAgentId)) {
      setActivePolicyAgentId(activeAgents[0].agentId);
    }
  }, [activeAgents, activePolicyAgentId]);

  useEffect(() => {
    if (activeToolId && !visibleTools.some((tool) => tool.id === activeToolId)) {
      setActiveToolId(visibleTools[0]?.id ?? null);
    }
  }, [activeToolId, visibleTools]);

  useEffect(() => {
    setSelectedToolIds((current) => {
      const visibleIds = new Set(visibleTools.map((tool) => tool.id));
      const next = new Set(Array.from(current).filter((toolId) => visibleIds.has(toolId)));
      return next.size === current.size ? current : next;
    });
  }, [visibleTools]);

  useEffect(() => {
    window.localStorage.setItem(TOOLS_LEFT_PANEL_WIDTH_KEY, String(leftPanelWidth));
  }, [leftPanelWidth]);

  const enableMutation = useMutation({
    mutationFn: (payload: { toolId: string; enabled: boolean }) =>
      fetchJson<ToolRegistryItem>(`/api/tools/generated/${encodeURIComponent(payload.toolId)}/enabled`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ enabled: payload.enabled }),
      }),
    onSuccess: (tool) => {
      setNotice({
        tone: "success",
        text: tool.enabled
          ? lang === "zh" ? `已启用 ${tool.name}` : `Enabled ${tool.name}`
          : lang === "zh" ? `已停用 ${tool.name}` : `Disabled ${tool.name}`,
      });
      refresh();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (toolId: string) =>
      fetchJson<GeneratedToolDeleteResponse>(`/api/tools/${encodeURIComponent(toolId)}`, {
        method: "DELETE",
      }),
    onSuccess: (payload) => {
      setNotice({ tone: "success", text: payload.summary });
      if (deleteMutation.variables === activeToolId) {
        setActiveToolId(null);
      }
      refresh();
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const testMutation = useMutation({
    mutationFn: (payload: { toolId: string; agentScopeId: string; agentId: string }) =>
      fetchJson<ToolTestResponse>(`/api/tools/${encodeURIComponent(payload.toolId)}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args: {}, agentScope: payload.agentScopeId, agentId: payload.agentId }),
      }),
    onSuccess: (payload, variables) => {
      setTestResult({
        key: toolTestKey(variables.toolId, variables.agentScopeId, variables.agentId),
        result: payload,
      });
      setNotice({
        tone: payload.status === "succeeded" ? "success" : "neutral",
        text: payload.message,
      });
    },
    onError: (error, variables) => {
      setTestResult((current) => (current?.key === toolTestKey(variables.toolId, variables.agentScopeId, variables.agentId) ? null : current));
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const image2ModelMutation = useMutation({
    mutationFn: (modelRef: string) =>
      fetchJson<ToolImage2ModelConfig>("/api/tools/image2/default-model", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ modelRef }),
      }),
    onSuccess: (payload) => {
      setNotice({
        tone: "success",
        text:
          lang === "zh"
            ? `已将 image2 工具模型切换为 ${image2ModelLabel(payload, lang)}`
            : `Updated image2 tool model to ${image2ModelLabel(payload, lang)}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.toolImage2Models() });
    },
    onError: (error) => {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const counts = toolsQuery.data?.counts;
  const activeIsGenerated = activeTool?.source === "generated";
  const activeToolTestKey = toolTestKey(activeTool?.id, activeAgentScope.id, activePolicyAgent?.agentId);
  const visibleTestResult = testResult?.key === activeToolTestKey ? testResult.result : null;
  const activeToolEnablePending = enableMutation.isPending && enableMutation.variables?.toolId === activeTool?.id;
  const activeToolDeletePending = deleteMutation.isPending && deleteMutation.variables === activeTool?.id;
  const activeToolTestPending = testMutation.isPending && toolTestKey(
    testMutation.variables?.toolId,
    testMutation.variables?.agentScopeId,
    testMutation.variables?.agentId,
  ) === activeToolTestKey;
  const activeCanDelete = Boolean(activeTool?.deleteAllowed) && !activeToolDeletePending;
  const activeCanToggle = Boolean(activeIsGenerated && activeTool?.validated && activeTool.status === "validated");
  const activeIsImage2Tool = activeTool?.name === IMAGE2_TOOL_NAME;
  const activeIsWebSearchTool = activeTool?.name === WEB_SEARCH_TOOL_NAME;
  const webSearchHealthQuery = useQuery({
    queryKey: queryKeys.toolWebSearchHealth(),
    queryFn: () => fetchJson<ToolDependencyHealth>("/api/tools/web-search/health"),
    enabled: activeIsWebSearchTool,
    refetchInterval: activeIsWebSearchTool ? resolvePollingInterval(pageVisible, 15_000) : false,
    refetchIntervalInBackground: false,
  });
  const webSearchHealth = webSearchHealthQuery.data;
  const image2ModelConfig = image2ModelsQuery.data;
  const workspaceStyle = useMemo(
    () =>
      ({
        "--tools-left-panel-width": leftPanelCollapsed ? "0px" : `${leftPanelWidth}px`,
      }) as CSSProperties,
    [leftPanelCollapsed, leftPanelWidth],
  );
  const resizeLeftPanelLabel = lang === "zh" ? "调整工具列表宽度" : "Resize tool list";

  function beginPanelResize(
    startX: number,
    currentWidth: number,
    bounds: { min: number; max: number },
    setter: (width: number) => void,
  ) {
    const startWidth = currentWidth;
    const handleMove = (moveEvent: globalThis.PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      setter(clampPaneWidth(startWidth + delta, bounds));
    };
    const handleEnd = () => {
      window.removeEventListener("pointermove", handleMove);
      window.removeEventListener("pointerup", handleEnd);
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
    window.addEventListener("pointermove", handleMove);
    window.addEventListener("pointerup", handleEnd);
  }

  function handleLeftPanelResizeStart(event: PointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) {
      return;
    }
    if (leftPanelCollapsed) {
      return;
    }
    event.preventDefault();
    beginPanelResize(event.clientX, leftPanelWidth, TOOLS_LEFT_PANEL_BOUNDS, setLeftPanelWidth);
  }

  function handleLeftPanelResizeKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    if (leftPanelCollapsed) {
      return;
    }
    const nextWidth = keyboardPaneWidth(leftPanelWidth, event.key, TOOLS_LEFT_PANEL_BOUNDS);
    if (nextWidth === null) {
      return;
    }
    event.preventDefault();
    setLeftPanelWidth(nextWidth);
  }

  function toggleBulkTool(toolId: string, selected: boolean) {
    setSelectedToolIds((current) => {
      const next = new Set(current);
      if (selected) {
        next.add(toolId);
      } else {
        next.delete(toolId);
      }
      return next;
    });
  }

  function selectVisibleBulkTools() {
    setSelectedToolIds(new Set(visibleTools.map((tool) => tool.id)));
  }

  function clearBulkTools() {
    setSelectedToolIds(new Set());
  }

  async function bulkSetToolsEnabled(enabled: boolean) {
    if (bulkToolPending) {
      return;
    }
    if (!selectedTools.length) {
      setNotice({ tone: "error", text: bulkCopy.noSelection });
      return;
    }
    setBulkToolPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    for (const tool of selectedTools) {
      if (!canBulkToggleTool(tool)) {
        skipped += 1;
        notes.push(`${tool.name}: ${bulkCopy.skippedToggle}`);
        continue;
      }
      try {
        await fetchJson<ToolRegistryItem>(`/api/tools/generated/${encodeURIComponent(tool.id)}/enabled`, {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ enabled }),
        });
        success += 1;
      } catch (error) {
        failed += 1;
        notes.push(`${tool.name}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    setBulkToolPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: toolsBulkActionSummary(enabled ? bulkCopy.enableResult : bulkCopy.disableResult, success, skipped, failed, notes, lang),
    });
    clearBulkTools();
    refresh();
  }

  async function bulkDeleteTools() {
    if (bulkToolPending) {
      return;
    }
    if (!selectedTools.length) {
      setNotice({ tone: "error", text: bulkCopy.noSelection });
      return;
    }
    const confirmed = window.confirm(bulkCopy.deleteConfirm);
    if (!confirmed) {
      return;
    }
    setBulkToolPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    let deletedActiveTool = false;
    for (const tool of selectedTools) {
      if (!tool.deleteAllowed) {
        skipped += 1;
        notes.push(`${tool.name}: ${bulkCopy.skippedDelete}`);
        continue;
      }
      try {
        await fetchJson<GeneratedToolDeleteResponse>(`/api/tools/${encodeURIComponent(tool.id)}`, {
          method: "DELETE",
        });
        if (tool.id === activeToolId) {
          deletedActiveTool = true;
        }
        success += 1;
      } catch (error) {
        failed += 1;
        notes.push(`${tool.name}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    if (deletedActiveTool) {
      setActiveToolId(null);
    }
    setBulkToolPending(false);
    setNotice({
      tone: failed > 0 ? "error" : "success",
      text: toolsBulkActionSummary(bulkCopy.deleteResult, success, skipped, failed, notes, lang),
    });
    clearBulkTools();
    refresh();
  }

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{t("navTools")}</p>
          <h1 className={styles.title}>{t("toolsPageTitle")}</h1>
          <p className={styles.subtitle}>{t("toolsPageSubtitle")}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {t("gitRefresh")}
        </button>
      </header>

      <div className={styles.controlStrip}>
        <AgentManagementNav active="tools" className={styles.managementNav} />

        <div className={styles.summaryGrid}>
          <section className={styles.summaryCard}>
            <span>{t("toolsTotal")}</span>
            <strong>{counts?.total ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{t("toolsBuiltIn")}</span>
            <strong>{counts?.builtIn ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{t("toolsGenerated")}</span>
            <strong>{counts?.generated ?? 0}</strong>
          </section>
          <section className={styles.summaryCard}>
            <span>{t("toolsLlmVisible")}</span>
            <strong>{counts?.llmVisible ?? 0}</strong>
          </section>
        </div>
      </div>

      <section className={styles.agentScopeBar}>
        <div className={styles.scopeCopy}>
          <p className={styles.panelEyebrow}>{t("toolsAgentScope")}</p>
          <strong>{scopeLabel(activeAgentScope, lang, t)}</strong>
          <span>{activeAgentScope.isSubagent ? t("toolsScopeModeReadonly") : activeAgentScope.mode}</span>
        </div>
        <label className={styles.scopeSelect}>
          <span>{t("toolsSelectedAgent")}</span>
          <select
            value={activeAgentScopeId}
            aria-label={t("toolsAgentScope")}
            onChange={(event) => setActiveAgentScopeId(event.target.value)}
          >
            {(agentScopes.length ? agentScopes : [activeAgentScope]).map((scope) => (
              <option key={scope.id} value={scope.id}>
                {scopeLabel(scope, lang, t)}
              </option>
            ))}
          </select>
        </label>
        <div className={styles.scopeStats}>
          <span>
            {t("toolsScopeVisible")}: <strong>{activeAgentScope.counts.visible}</strong>
          </span>
          <span>
            {t("toolsScopeCallable")}: <strong>{activeAgentScope.counts.callable}</strong>
          </span>
          <span>
            {t("toolsScopeBlocked")}: <strong>{activeAgentScope.counts.blocked}</strong>
          </span>
        </div>
      </section>

      <div className={styles.workspace} style={workspaceStyle}>
        <aside className={leftPanelCollapsed ? `${styles.listPanel} ${styles.paneCollapsed}` : styles.listPanel} aria-hidden={leftPanelCollapsed}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{t("toolsRegistry")}</p>
              <h2>{t("toolsCurrentAgentTools")}</h2>
            </div>
            <span className={styles.countPill}>{visibleTools.length}</span>
          </div>
          <label className={styles.searchBox}>
            <Search size={15} />
            <input
              value={searchText}
              placeholder={t("toolsSearchPlaceholder")}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>
          <div className={styles.filterRow}>
            {FILTERS.map((filter) => (
              <button
                key={filter}
                type="button"
                className={filter === activeFilter ? styles.filterButtonActive : styles.filterButton}
                onClick={() => setActiveFilter(filter)}
              >
                <span>{filterLabel(filter, lang)}</span>
                <strong>{filterCounts[filter]}</strong>
              </button>
            ))}
          </div>
          <section className={styles.bulkActionBar} aria-label={bulkCopy.selected}>
            <div className={styles.bulkSummary}>
              <CheckSquare size={15} />
              <strong>{bulkCopy.selected}</strong>
              <span>{selectedTools.length} / {visibleTools.length}</span>
            </div>
            <button
              type="button"
              className={styles.secondaryButton}
              disabled={!visibleTools.length || bulkToolPending}
              onClick={allVisibleToolsSelected ? clearBulkTools : selectVisibleBulkTools}
            >
              {allVisibleToolsSelected ? <Square size={14} /> : <CheckSquare size={14} />}
              <span>{allVisibleToolsSelected ? bulkCopy.clear : bulkCopy.selectVisible}</span>
            </button>
            <button type="button" className={styles.primaryButton} disabled={!selectedTools.length || bulkToolPending} onClick={() => bulkSetToolsEnabled(true)}>
              <Power size={14} />
              <span>{bulkToolPending ? bulkCopy.working : bulkCopy.enable}</span>
            </button>
            <button type="button" className={styles.secondaryButton} disabled={!selectedTools.length || bulkToolPending} onClick={() => bulkSetToolsEnabled(false)}>
              <CircleSlash size={14} />
              <span>{bulkToolPending ? bulkCopy.working : bulkCopy.disable}</span>
            </button>
            <button type="button" className={styles.secondaryButton} disabled={!selectedTools.length || bulkToolPending} onClick={bulkDeleteTools}>
              <Trash2 size={14} />
              <span>{bulkToolPending ? bulkCopy.working : bulkCopy.delete}</span>
            </button>
          </section>
          <div className={styles.toolList}>
            {visibleToolBundleGroups.map((group) => (
              <section key={group.bundleId} className={styles.toolBundleGroup}>
                <header className={styles.toolBundleHeader}>
                  <div>
                    <strong>{group.label}</strong>
                    <span>{group.tools.length} tools</span>
                  </div>
                  <small>
                    {lang === "zh" ? "高风险" : "High risk"} {group.highRiskToolCount} · {lang === "zh" ? "显式授权" : "Explicit"} {group.explicitAllowToolCount}
                  </small>
                </header>
                {group.description ? <p className={styles.toolBundleDescription}>{group.description}</p> : null}
                <div className={styles.toolBundleItems}>
                  {group.tools.map((tool) => {
                    const isActive = tool.id === activeTool?.id;
                    const policyMode = activePolicyAgent ? toolPolicyMode(activePolicy, tool) : "inherited";
                    const bulkSelected = selectedToolIds.has(tool.id);
                    return (
                      <div key={`${group.bundleId}-${tool.source}-${tool.id}`} className={styles.selectableToolRow}>
                        <label className={styles.rowSelect} title={`${bulkCopy.selected}: ${tool.name}`}>
                          <input
                            type="checkbox"
                            checked={bulkSelected}
                            aria-label={`${bulkCopy.selected}: ${tool.name}`}
                            onChange={(event) => toggleBulkTool(tool.id, event.target.checked)}
                          />
                          {bulkSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                        </label>
                        <button
                        type="button"
                        className={isActive ? styles.toolButtonActive : styles.toolButton}
                        onClick={() => setActiveToolId(tool.id)}
                      >
                        <span className={`${styles.statusDot} ${styles[`status_${statusTone(tool)}`]}`} />
                        <span className={styles.toolCopy}>
                          <strong>{tool.name}</strong>
                          <span>{tool.description || t("toolsNoDescription")}</span>
                        </span>
                        <span className={styles.toolBadges}>
                          <span className={`${styles.policyStatePill} ${styles[`policy_${policyMode}`]}`}>
                            {toolPolicyModeLabel(policyMode, lang)}
                          </span>
                          <span className={styles.sourcePill}>{displaySource(tool.source, lang)}</span>
                        </span>
                        </button>
                      </div>
                    );
                  })}
                </div>
              </section>
            ))}
            {!visibleTools.length ? <p className={styles.emptyState}>{t("toolsNoMatches")}</p> : null}
          </div>
        </aside>

        <PaneCollapseHandle
          side="left"
          collapsed={leftPanelCollapsed}
          separatorLabel={resizeLeftPanelLabel}
          collapseLabel={lang === "zh" ? "收起工具列表" : "Collapse tool list"}
          expandLabel={lang === "zh" ? "展开工具列表" : "Expand tool list"}
          className={styles.resizeHandle}
          onToggle={() => setLeftPanelCollapsed((current) => !current)}
          onPointerDown={handleLeftPanelResizeStart}
          onKeyDown={handleLeftPanelResizeKeyDown}
        />

        <main className={styles.detailPanel}>
          <section className={styles.agentPermissionSummaryPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{lang === "zh" ? "Agent 权限边界" : "Agent permission boundary"}</p>
                <h2>{lang === "zh" ? "这里用于测试工具，不在这里配置 Agent" : "Test tools here, configure Agents in Agent Center"}</h2>
              </div>
              <span className={styles.countPill}>{lang === "zh" ? "编辑入口在 Agent 管理" : "Edit in Agent Center"}</span>
            </div>
            <div className={styles.permissionSummaryGrid}>
              <label className={styles.agentPolicySelect}>
                <span>{lang === "zh" ? "测试 Agent" : "Test Agent"}</span>
                <select
                  value={activePolicyAgent?.agentId ?? ""}
                  disabled={!activeAgents.length}
                  onChange={(event) => setActivePolicyAgentId(event.target.value)}
                >
                  {!activeAgents.length ? (
                    <option value="">{agentsQuery.isPending ? t("loading") : "-"}</option>
                  ) : null}
                  {activeAgents.map((agent) => (
                    <option key={agent.agentId} value={agent.agentId}>
                      {agent.agentCode ? `${agent.agentCode} · ` : ""}{agent.displayName || agent.agentId}
                    </option>
                  ))}
                </select>
              </label>
              <div className={styles.permissionSummaryCards}>
                <span>{lang === "zh" ? "允许" : "Allowed"} <strong>{policyModeCounts.allowed}</strong></span>
                <span>{lang === "zh" ? "禁用" : "Blocked"} <strong>{policyModeCounts.blocked}</strong></span>
                <span>{lang === "zh" ? "默认" : "Default"} <strong>{policyModeCounts.inherited}</strong></span>
                <span>{lang === "zh" ? "需授权" : "Explicit"} <strong>{policyModeCounts.explicit_required}</strong></span>
                <span>{lang === "zh" ? "未列入" : "Excluded"} <strong>{policyModeCounts.excluded}</strong></span>
              </div>
              <Link className={styles.secondaryButton} to="/agents">
                <Wrench size={15} />
                {lang === "zh" ? "去 Agent 中心配置" : "Configure in Agent Center"}
              </Link>
            </div>
          </section>
          {activeTool ? (
            <>
              <section className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>
                    {displaySource(activeTool.source, lang)} / {scopeLabel(activeAgentScope, lang, t)}
                  </p>
                  <h2>{activeTool.name}</h2>
                  <p>{activeTool.description || t("toolsNoDescription")}</p>
                </div>
                <span className={`${styles.stateBadge} ${styles[`state_${statusTone(activeTool)}`]}`}>
                  {activeTool.status}
                </span>
              </section>
              <div className={styles.metaGrid}>
                <section>
                  <span>{t("toolsScopeVisible")}</span>
                  <strong>{activeScopeState?.visible ? t("yes") : t("no")}</strong>
                </section>
                <section>
                  <span>{t("toolsScopeCallable")}</span>
                  <strong>{activeScopeState?.callable ? t("yes") : t("no")}</strong>
                </section>
                <section>
                  <span>{t("toolsLlmVisible")}</span>
                  <strong>{activeScopeState?.llmVisible ? t("yes") : t("no")}</strong>
                </section>
                <section>
                  <span>{t("toolsDeleteAllowed")}</span>
                  <strong>{activeTool.deleteAllowed ? t("yes") : t("no")}</strong>
                </section>
                <section className={styles.metaGridWide}>
                  <span>{lang === "zh" ? "所属工具包" : "Tool packages"}</span>
                  <strong>{activeToolBundleLabels.join(" / ")}</strong>
                </section>
              </div>
              {activeScopeState?.blockReason || activeTool.blockReason || activeTool.validationError ? (
                <p className={styles.notice}>
                  {activeScopeState?.blockReason || activeTool.blockReason || activeTool.validationError}
                </p>
              ) : null}
              <section className={styles.readinessPanel}>
                {toolReadinessCards(activeTool, activeScopeState ?? scopeStateForTool(activeTool, activeAgentScope.id), activeAgentScope, t).map((card) => (
                  <div
                    key={card.key}
                    className={`${styles.readinessCard} ${styles[`readiness_${readinessTone(card.ready)}`]}`}
                  >
                    <span>{card.label}</span>
                    <strong>{card.value}</strong>
                  </div>
                ))}
              </section>
              <section className={styles.toolAgentFitPanel}>
                <div>
                  <p className={styles.panelEyebrow}>{lang === "zh" ? "当前测试边界" : "Current test boundary"}</p>
                  <h3>{activePolicyAgent ? `${activePolicyAgent.agentCode || ""} ${activePolicyAgent.displayName || activePolicyAgent.agentId}`.trim() : "-"}</h3>
                  <span>{activePolicy.policyId || activePolicyAgent?.toolPolicyId || "-"}</span>
                </div>
                <strong className={`${styles.policyStatePill} ${styles[`policy_${activePolicyMode}`]}`}>
                  {toolPolicyModeLabel(activePolicyMode, lang)}
                </strong>
                <Link className={styles.secondaryButton} to="/agents">
                  <Wrench size={15} />
                  {lang === "zh" ? "编辑 Agent 策略" : "Edit Agent policy"}
                </Link>
              </section>
              {activeIsImage2Tool ? (
                <section className={styles.image2ModelPanel}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{lang === "zh" ? "模型选择" : "Model selection"}</p>
                      <h3>{lang === "zh" ? "image2 工具模型" : "image2 tool model"}</h3>
                    </div>
                    <span className={styles.countPill}>
                      {image2ModelConfig?.models.length ?? 0}
                    </span>
                  </div>
                  <div className={styles.image2ModelControls}>
                    <label className={styles.image2ModelSelect}>
                      <span>{lang === "zh" ? "使用模型" : "Model"}</span>
                      <select
                        value={image2ModelConfig?.defaultModelRef ?? ""}
                        disabled={image2ModelsQuery.isPending || image2ModelMutation.isPending}
                        onChange={(event) => image2ModelMutation.mutate(event.target.value)}
                      >
                        <option value="">
                          {lang === "zh" ? "未设置（环境变量/内置回退）" : "Not set (env/built-in fallback)"}
                        </option>
                        {(image2ModelConfig?.models ?? []).map((model) => (
                          <option key={model.modelRef} value={model.modelRef}>
                            {model.label || model.modelRef}
                          </option>
                        ))}
                      </select>
                    </label>
                    <div className={styles.image2ModelSummary}>
                      <strong>{image2ModelLabel(image2ModelConfig, lang)}</strong>
                      <span>{image2ModelConfig?.selectedModel.resolvedModel || image2ModelConfig?.fallbackModel.resolvedModel || "-"}</span>
                    </div>
                  </div>
                  <div className={styles.policyMeta}>
                    <span>
                      provider: <strong>{image2ModelConfig?.selectedModel.providerKind || "-"}</strong>
                    </span>
                    <span>
                      modelRef: <strong>{image2ModelConfig?.defaultModelRef || "-"}</strong>
                    </span>
                    <span>
                      apiKeyEnv: <strong>{image2ModelConfig?.selectedModel.apiKeyEnv || "-"}</strong>
                    </span>
                    <span>
                      {lang === "zh" ? "密钥状态" : "key"}:{" "}
                      <strong>{image2KeyStateLabel(image2ModelConfig, lang)}</strong>
                    </span>
                    <span>
                      {lang === "zh" ? "配置模型" : "configured"}:{" "}
                      <strong>{image2ModelConfig?.selectedModel.configuredModel || "-"}</strong>
                    </span>
                    <span>
                      {lang === "zh" ? "实际请求" : "request model"}:{" "}
                      <strong>{image2ModelConfig?.selectedModel.resolvedModel || "-"}</strong>
                    </span>
                    <span>
                      {lang === "zh" ? "远端发现" : "discovery"}:{" "}
                      <strong>{image2DiscoveryStateLabel(image2ModelConfig, lang)}</strong>
                    </span>
                  </div>
                  <p>
                    {lang === "zh"
                      ? "这里只选择设置页模型库条目；生成请求仍使用配置的根 base_url，模型名会在调用前按远端 /v1/models 发现结果解析。"
                      : "This selects a Settings model entry. Generation still uses the configured root base_url, while the request model is resolved from remote /v1/models when needed."}
                  </p>
                  {image2ModelConfig?.selectedModel.modelDiscoveryError ? (
                    <p className={styles.noticeError}>{image2ModelConfig.selectedModel.modelDiscoveryError}</p>
                  ) : null}
                  {image2ModelsQuery.isError ? (
                    <p className={styles.noticeError}>
                      {image2ModelsQuery.error instanceof Error ? image2ModelsQuery.error.message : String(image2ModelsQuery.error)}
                    </p>
                  ) : null}
                </section>
              ) : null}
              {activeIsWebSearchTool ? (
                <section className={styles.dependencyHealthPanel}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>
                        {lang === "zh" ? "外部依赖" : "External dependency"}
                      </p>
                      <h3>{lang === "zh" ? "AutoGLM token 服务" : "AutoGLM token service"}</h3>
                    </div>
                    <span className={webSearchHealth?.available ? styles.countPill : styles.stateBadge}>
                      {webSearchHealthQuery.isPending
                        ? t("loading")
                        : webSearchHealth?.available
                          ? lang === "zh" ? "可用" : "available"
                          : webSearchHealth?.status || (lang === "zh" ? "不可用" : "unavailable")}
                    </span>
                  </div>
                  <div className={styles.policyMeta}>
                    <span>
                      dependency: <strong>{webSearchHealth?.dependency || "autoglm_token_service"}</strong>
                    </span>
                    <span>
                      stage: <strong>{webSearchHealth?.stage || "token_fetch"}</strong>
                    </span>
                    <span>
                      tokenUrl: <strong>{webSearchHealth?.tokenUrl || "-"}</strong>
                    </span>
                    <span>
                      searchApiCalled:{" "}
                      <strong>{webSearchHealth?.searchApiCalled === undefined ? "-" : String(webSearchHealth.searchApiCalled)}</strong>
                    </span>
                  </div>
                  <p>
                    {webSearchHealth?.available
                      ? lang === "zh"
                        ? "搜索工具已能取得本地 token，后续调用才会进入 AutoGLM 搜索 API。"
                        : "The search tool can obtain a local token, so calls may proceed to the AutoGLM search API."
                      : lang === "zh"
                        ? "搜索工具会先依赖这个本地 token 服务；这里不可用时，外网搜索 API 不会被调用。端口变化可用 AUTOGLM_TOKEN_URL 覆盖。"
                        : "The search tool depends on this local token service first. When it is unavailable, the external search API is not called. Use AUTOGLM_TOKEN_URL if the port changed."}
                  </p>
                  {webSearchHealthQuery.isError ? (
                    <p className={styles.noticeError}>
                      {webSearchHealthQuery.error instanceof Error ? webSearchHealthQuery.error.message : String(webSearchHealthQuery.error)}
                    </p>
                  ) : null}
                </section>
              ) : null}
              <section className={styles.policyPanel}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{t("toolsTestPolicy")}</p>
                    <h3>{testPolicyLabel(activeTool.testPolicy.mode, lang)}</h3>
                  </div>
                  <span className={activeTool.testPolicy.callable ? styles.countPill : styles.stateBadge}>
                    {activeTool.testPolicy.callable ? t("yes") : t("no")}
                  </span>
                </div>
                <div className={styles.policyMeta}>
                  <span>
                    {t("toolsRuntimeCall")}: <strong>{activeTool.testPolicy.runtimeCall ? t("yes") : t("no")}</strong>
                  </span>
                  <span>
                    {t("toolsSimulatedCall")}: <strong>{activeTool.testPolicy.simulated ? t("yes") : t("no")}</strong>
                  </span>
                </div>
                <p>{activeTool.testPolicy.reason}</p>
                <pre>{jsonPreview(activeTool.testPolicy.argsPreview)}</pre>
              </section>
              <div className={styles.detailActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!activeCanToggle || activeToolEnablePending}
                  onClick={() => {
                    if (!activeTool) {
                      return;
                    }
                    enableMutation.mutate({ toolId: activeTool.id, enabled: !activeTool.enabled });
                  }}
                  title={activeCanToggle ? undefined : activeTool.blockReason || t("toolsEnableBlocked")}
                >
                  {activeTool.enabled ? <CircleSlash size={15} /> : <Power size={15} />}
                  {activeTool.enabled ? t("toolsDisable") : t("toolsEnable")}
                </button>
                <button
                  type="button"
                  className={styles.dangerButton}
                  disabled={!activeCanDelete}
                  onClick={() => {
                    if (activeTool) {
                      const confirmed = window.confirm(
                        lang === "zh"
                          ? `确认删除工具 ${activeTool.name}？`
                          : `Delete tool ${activeTool.name}?`,
                      );
                      if (!confirmed) {
                        return;
                      }
                      deleteMutation.mutate(activeTool.id);
                    }
                  }}
                  title={activeTool.deleteAllowed ? undefined : activeTool.blockReason || t("toolsBuiltInProtected")}
                >
                  <Trash2 size={15} />
                  {activeToolDeletePending ? t("deletingSelectedLogs") : t("deleteSelected")}
                </button>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!activeTool || !activePolicyAgent || activeToolTestPending}
                  onClick={() => {
                    if (activeTool && activePolicyAgent) {
                      testMutation.mutate({
                        toolId: activeTool.id,
                        agentScopeId: activeAgentScope.id,
                        agentId: activePolicyAgent.agentId,
                      });
                    }
                  }}
                >
                  <FlaskConical size={15} />
                  {activeToolTestPending ? t("toolsTesting") : t("toolsTest")}
                </button>
              </div>
              {notice.text ? (
                <p
                  className={
                    notice.tone === "error"
                      ? styles.noticeError
                      : notice.tone === "success"
                        ? styles.noticeSuccess
                        : styles.notice
                  }
                >
                  {notice.text}
                </p>
              ) : null}
              {visibleTestResult ? (
                <section className={styles.testPanel}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{t("toolsTestResult")}</p>
                      <h3>{visibleTestResult.status}</h3>
                    </div>
                    <span className={styles.countPill}>{agentTestLabel(visibleTestResult.agent, lang)}</span>
                  </div>
                  <p>{visibleTestResult.message}</p>
                  <div className={styles.policyMeta}>
                    <span>
                      {t("toolsAgentScope")}: <strong>{scopeLabel(visibleTestResult.agentScope, lang, t)}</strong>
                    </span>
                    <span>
                      ToolPolicy: <strong>{visibleTestResult.agent?.toolPolicyId || "-"}</strong>
                    </span>
                  </div>
                  <div className={styles.resultSummaryGrid}>
                    {testResultSummaryCards(visibleTestResult, t).map((card) => (
                      <div key={card.key} className={`${styles.resultCard} ${card.ok ? styles.result_ok : styles.result_attention}`}>
                        <span>{card.label}</span>
                        <strong>{card.value}</strong>
                      </div>
                    ))}
                  </div>
                  <section className={styles.agentCompatibility}>
                    <div className={styles.panelHeader}>
                      <div>
                        <p className={styles.panelEyebrow}>{t("toolsAgentCompatibility")}</p>
                        <h3>{visibleTestResult.agentCompatibility.status}</h3>
                      </div>
                      <span className={visibleTestResult.agentCompatibility.callable ? styles.countPill : styles.stateBadge}>
                        {visibleTestResult.agentCompatibility.callable ? t("yes") : t("no")}
                      </span>
                    </div>
                    <p>{visibleTestResult.agentCompatibility.message}</p>
                    <div className={styles.policyMeta}>
                      <span>
                        {t("toolsAgentMessageType")}:{" "}
                        <strong>{visibleTestResult.agentCompatibility.messageType || "-"}</strong>
                      </span>
                      <span>
                        {t("toolsAgentToolCall")}: <strong>{visibleTestResult.agentCompatibility.toolCall.name}</strong>
                      </span>
                    </div>
                    <pre>{jsonPreview(visibleTestResult.agentCompatibility.argsParsed)}</pre>
                  </section>
                  {visibleTestResult.resultPreview ? <pre>{visibleTestResult.resultPreview}</pre> : null}
                  <div className={styles.testArgs}>
                    <span>{t("toolsArgsUsed")}</span>
                    <pre>{jsonPreview(visibleTestResult.argsUsed)}</pre>
                  </div>
                </section>
              ) : null}
              <details className={styles.schemaDisclosure}>
                <summary>
                  <span>
                    <span className={styles.panelEyebrow}>{t("toolsArgsSchema")}</span>
                    <strong>{t("toolsShowSchema")}</strong>
                  </span>
                  {activeTool.validated ? <CheckCircle2 size={17} /> : <CircleSlash size={17} />}
                </summary>
                <pre>{schemaPreview(activeTool)}</pre>
              </details>
            </>
          ) : (
            <section className={styles.emptyDetail}>
              <Wrench size={24} />
              <strong>{t("toolsCurrentAgentTools")}</strong>
              <p>{toolsQuery.isPending ? t("loading") : t("toolsNoMatches")}</p>
            </section>
          )}
        </main>
      </div>
    </section>
  );
}
