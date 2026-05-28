import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, FlaskConical, ListChecks, Power, RefreshCw, RotateCcw, Save, Search, Trash2, Wrench, X } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  AgentInstance,
  GeneratedToolDeleteResponse,
  ToolAgentScopeState,
  ToolAgentScopeSummary,
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
type EditableToolPolicyMode = "inherited" | "allowed" | "blocked";
type ToolPermissionFilter = "all" | ToolPolicyMode;
type Translate = (key: TranslationKey) => string;

const FILTERS: ToolFilter[] = ["all", "built_in", "generated", "llm", "enabled"];
const PERMISSION_FILTERS: ToolPermissionFilter[] = ["all", "allowed", "blocked", "explicit_required", "inherited", "excluded"];
const TOOLS_LEFT_PANEL_WIDTH_KEY = "vibelution.tools.left-panel-width";
const TOOLS_LEFT_PANEL_BOUNDS = { min: 260, max: 520 };
const TOOLS_LEFT_PANEL_DEFAULT_WIDTH = 350;
const MAIN_AGENT_SCOPE_ID = "main_agent";
const IMAGE2_TOOL_NAME = "image2_generate_tool";

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

function permissionFilterLabel(filter: ToolPermissionFilter, lang: string) {
  if (filter === "all") {
    return lang === "zh" ? "全部权限" : "All states";
  }
  return toolPolicyModeLabel(filter, lang);
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

function uniqueToolList(values: string[]) {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean))).sort();
}

function copyToolPolicy(policy: ToolPolicy): ToolPolicy {
  const normalized = {
    ...defaultToolPolicy(policy.policyId),
    ...policy,
  };
  return {
    ...normalized,
    allowedTools: [...(normalized.allowedTools ?? [])],
    preferredTools: [...(normalized.preferredTools ?? [])],
    blockedTools: [...(normalized.blockedTools ?? [])],
    readScopes: [...(normalized.readScopes ?? [])],
    writeScopes: [...(normalized.writeScopes ?? [])],
    allowedCommandKinds: [...(normalized.allowedCommandKinds ?? [])],
    blockedCommandPatterns: [...(normalized.blockedCommandPatterns ?? [])],
    perToolRules: { ...(normalized.perToolRules ?? {}) },
  };
}

function toolPolicyListSignature(values?: string[]) {
  return uniqueToolList(values ?? []).join("\n");
}

function toolPolicyDraftDirty(base: ToolPolicy, draft: ToolPolicy | null) {
  if (!draft) {
    return false;
  }
  return (
    toolPolicyListSignature(base.allowedTools) !== toolPolicyListSignature(draft.allowedTools) ||
    toolPolicyListSignature(base.blockedTools) !== toolPolicyListSignature(draft.blockedTools)
  );
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

function toolPolicyModeReason(mode: ToolPolicyMode, lang: string) {
  const zh = {
    inherited: "该工具未被当前 Agent 单独限制。",
    explicit_required: "该工具是受限能力，只有加入允许清单后才会对当前 Agent 可见并可调用。",
    allowed: "该工具在当前 Agent 的允许清单中。",
    blocked: "该工具被当前 Agent 禁用，测试不会执行。",
    excluded: "当前 Agent 使用允许清单，该工具未被列入。",
  };
  const en = {
    inherited: "This tool is not individually restricted for the selected Agent.",
    explicit_required: "This restricted tool stays hidden and blocked until this Agent explicitly allows it.",
    allowed: "This tool is in the selected Agent allow-list.",
    blocked: "This tool is blocked for the selected Agent; tests will not execute it.",
    excluded: "The selected Agent uses an allow-list and this tool is not included.",
  };
  return (lang === "zh" ? zh : en)[mode];
}

function nextToolPolicy(policy: ToolPolicy, toolName: string, mode: EditableToolPolicyMode): ToolPolicy {
  const allowed = new Set(policy.allowedTools ?? []);
  const blocked = new Set(policy.blockedTools ?? []);
  allowed.delete(toolName);
  blocked.delete(toolName);
  if (mode === "allowed") {
    allowed.add(toolName);
  }
  if (mode === "blocked") {
    blocked.add(toolName);
  }
  return {
    ...defaultToolPolicy(policy.policyId),
    ...policy,
    allowedTools: uniqueToolList(Array.from(allowed)),
    blockedTools: uniqueToolList(Array.from(blocked)),
  };
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

export function ToolsRoute() {
  const { lang, t } = useAppI18n();
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<ToolFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [activeAgentScopeId, setActiveAgentScopeId] = useState(MAIN_AGENT_SCOPE_ID);
  const [activePolicyAgentId, setActivePolicyAgentId] = useState("");
  const [policyDraft, setPolicyDraft] = useState<ToolPolicy | null>(null);
  const [permissionFilter, setPermissionFilter] = useState<ToolPermissionFilter>("all");
  const [permissionSearchText, setPermissionSearchText] = useState("");
  const [selectedPolicyToolNames, setSelectedPolicyToolNames] = useState<string[]>([]);
  const [activeToolId, setActiveToolId] = useState<string | null>(null);
  const [leftPanelWidth, setLeftPanelWidth] = useState(() =>
    storedPaneWidth(TOOLS_LEFT_PANEL_WIDTH_KEY, TOOLS_LEFT_PANEL_DEFAULT_WIDTH, TOOLS_LEFT_PANEL_BOUNDS),
  );
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [notice, setNotice] = useState<{ tone: "neutral" | "success" | "error"; text: string }>({
    tone: "neutral",
    text: "",
  });
  const [testResult, setTestResult] = useState<ToolTestResponse | null>(null);
  const pageVisible = usePageVisibility();

  const toolsQuery = useQuery({
    queryKey: queryKeys.tools(),
    queryFn: () => fetchJson<ToolRegistryPayload>("/api/tools"),
    refetchInterval: resolvePollingInterval(pageVisible, 8_000),
    refetchIntervalInBackground: false,
  });

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents"),
    refetchInterval: resolvePollingInterval(pageVisible, 12_000),
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
    void queryClient.invalidateQueries({ queryKey: queryKeys.toolImage2Models() });
  };

  const tools = toolsQuery.data?.tools ?? [];
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
      return `${tool.name} ${tool.description} ${tool.source} ${tool.status}`.toLowerCase().includes(query);
    });
  }, [activeAgentScopeId, activeFilter, searchText, tools]);
  const activeTool = tools.find((tool) => tool.id === activeToolId) ?? visibleTools[0] ?? null;
  const activeScopeState = activeTool ? scopeStateForTool(activeTool, activeAgentScope.id) : null;
  const activeAgents = useMemo(
    () => (agentsQuery.data ?? []).filter((agent) => agent.status !== "archived"),
    [agentsQuery.data],
  );
  const activePolicyAgent = activeAgents.find((agent) => agent.agentId === activePolicyAgentId) ?? activeAgents[0] ?? null;
  const activePolicy = toolPolicyForAgent(activePolicyAgent);
  const activePolicyBaseSignature = `${activePolicyAgent?.agentId ?? ""}:${activePolicy.policyId}:${toolPolicyListSignature(activePolicy.allowedTools)}:${toolPolicyListSignature(activePolicy.blockedTools)}`;
  const effectivePolicy = policyDraft ?? activePolicy;
  const policyDirty = toolPolicyDraftDirty(activePolicy, policyDraft);
  const activePolicyMode = activeTool && activePolicyAgent ? toolPolicyMode(effectivePolicy, activeTool) : "inherited";
  const policyModeCounts = useMemo(() => toolPolicyModeCounts(effectivePolicy, tools), [effectivePolicy, tools]);
  const selectedPolicyToolNameSet = useMemo(() => new Set(selectedPolicyToolNames), [selectedPolicyToolNames]);
  const permissionTools = useMemo(() => {
    const query = permissionSearchText.trim().toLowerCase();
    return tools.filter((tool) => {
      const mode = toolPolicyMode(effectivePolicy, tool);
      if (permissionFilter !== "all" && mode !== permissionFilter) {
        return false;
      }
      if (!query) {
        return true;
      }
      return `${tool.name} ${tool.description} ${tool.source} ${tool.status}`.toLowerCase().includes(query);
    });
  }, [effectivePolicy, permissionFilter, permissionSearchText, tools]);
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
    setTestResult(null);
  }, [activeAgentScopeId, activePolicyAgentId, activeToolId]);

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
    setPolicyDraft(activePolicyAgent ? copyToolPolicy(activePolicy) : null);
    setSelectedPolicyToolNames([]);
  }, [activePolicyAgent?.agentId]);

  useEffect(() => {
    setPolicyDraft((current) => {
      if (!activePolicyAgent) {
        return null;
      }
      if (current && toolPolicyDraftDirty(activePolicy, current)) {
        return current;
      }
      return copyToolPolicy(activePolicy);
    });
  }, [activePolicyAgent?.agentId, activePolicyBaseSignature]);

  useEffect(() => {
    const knownToolNames = new Set(tools.map((tool) => tool.name));
    setSelectedPolicyToolNames((current) => current.filter((toolName) => knownToolNames.has(toolName)));
  }, [tools]);

  useEffect(() => {
    if (activeToolId && !visibleTools.some((tool) => tool.id === activeToolId)) {
      setActiveToolId(visibleTools[0]?.id ?? null);
    }
  }, [activeToolId, visibleTools]);

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
      setActiveToolId(null);
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
    onSuccess: (payload) => {
      setTestResult(payload);
      setNotice({
        tone: payload.status === "succeeded" ? "success" : "neutral",
        text: payload.message,
      });
    },
    onError: (error) => {
      setTestResult(null);
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    },
  });

  const toolPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; policy: ToolPolicy }) =>
      fetchJson<AgentInstance>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ toolPolicy: payload.policy }),
      }),
    onSuccess: (agent) => {
      setNotice({
        tone: "success",
        text: lang === "zh" ? `已更新 ${agent.displayName || agent.agentCode} 的工具权限` : `Updated tool permissions for ${agent.displayName || agent.agentCode}`,
      });
      queryClient.setQueryData<AgentInstance[]>(queryKeys.agents(), (current) =>
        current?.map((item) => (item.agentId === agent.agentId ? agent : item)),
      );
      if (agent.agentId === activePolicyAgent?.agentId) {
        setPolicyDraft(copyToolPolicy(toolPolicyForAgent(agent)));
        setSelectedPolicyToolNames([]);
      }
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
    },
    onError: (error) => {
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
  const activeCanDelete = Boolean(activeTool?.deleteAllowed) && !deleteMutation.isPending;
  const activeCanToggle = Boolean(activeIsGenerated && activeTool?.validated && activeTool.status === "validated");
  const activeIsImage2Tool = activeTool?.name === IMAGE2_TOOL_NAME;
  const image2ModelConfig = image2ModelsQuery.data;
  const selectedPolicyCount = selectedPolicyToolNames.length;
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

  function updateActiveToolPolicy(mode: EditableToolPolicyMode) {
    if (!activeTool || !activePolicyAgent) {
      return;
    }
    setPolicyDraft((current) => nextToolPolicy(current ?? activePolicy, activeTool.name, mode));
  }

  function togglePolicyToolSelection(toolName: string) {
    setSelectedPolicyToolNames((current) =>
      current.includes(toolName) ? current.filter((name) => name !== toolName) : uniqueToolList([...current, toolName]),
    );
  }

  function selectVisiblePolicyTools() {
    setSelectedPolicyToolNames((current) => uniqueToolList([...current, ...permissionTools.map((tool) => tool.name)]));
  }

  function setSelectedToolsPolicyMode(mode: EditableToolPolicyMode) {
    if (!activePolicyAgent || !selectedPolicyToolNames.length) {
      return;
    }
    setPolicyDraft((current) =>
      selectedPolicyToolNames.reduce(
        (policy, toolName) => nextToolPolicy(policy, toolName, mode),
        current ?? activePolicy,
      ),
    );
  }

  function clearPolicyList(listName: "allowed" | "blocked") {
    if (!activePolicyAgent) {
      return;
    }
    setPolicyDraft((current) => {
      const nextPolicy = copyToolPolicy(current ?? activePolicy);
      if (listName === "allowed") {
        nextPolicy.allowedTools = [];
      } else {
        nextPolicy.blockedTools = [];
      }
      return nextPolicy;
    });
  }

  function resetPolicyDraft() {
    setPolicyDraft(activePolicyAgent ? copyToolPolicy(activePolicy) : null);
    setSelectedPolicyToolNames([]);
  }

  function applyPolicyDraft() {
    if (!activePolicyAgent || !policyDraft || !policyDirty) {
      return;
    }
    toolPolicyMutation.mutate({
      agentId: activePolicyAgent.agentId,
      policy: copyToolPolicy(policyDraft),
    });
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
          <div className={styles.toolList}>
            {visibleTools.map((tool) => {
              const isActive = tool.id === activeTool?.id;
              const policyMode = activePolicyAgent ? toolPolicyMode(effectivePolicy, tool) : "inherited";
              return (
                <button
                  key={`${tool.source}-${tool.id}`}
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
              );
            })}
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
          <section className={styles.agentBulkPolicyPanel}>
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{lang === "zh" ? "Agent 工具权限" : "Agent tool permissions"}</p>
                <h2>{lang === "zh" ? "批量分配工具权限" : "Bulk assign tool permissions"}</h2>
              </div>
              <span className={policyDirty ? styles.unsavedPill : styles.countPill}>
                {policyDirty ? (lang === "zh" ? "有未应用修改" : "Unsaved draft") : (lang === "zh" ? "已同步" : "Synced")}
              </span>
            </div>
            <div className={styles.bulkPolicyTopRow}>
              <label className={styles.agentPolicySelect}>
                <span>{lang === "zh" ? "当前 Agent" : "Current Agent"}</span>
                <select
                  value={activePolicyAgent?.agentId ?? ""}
                  disabled={!activeAgents.length || policyDirty || toolPolicyMutation.isPending}
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
              <div className={styles.policyMeta}>
                <span>
                  allowed: <strong>{policyModeCounts.allowed}</strong>
                </span>
                <span>
                  blocked: <strong>{policyModeCounts.blocked}</strong>
                </span>
                <span>
                  inherited: <strong>{policyModeCounts.inherited}</strong>
                </span>
                <span>
                  {lang === "zh" ? "需授权" : "explicit"}: <strong>{policyModeCounts.explicit_required}</strong>
                </span>
                <span>
                  excluded: <strong>{policyModeCounts.excluded}</strong>
                </span>
              </div>
            </div>
            <div className={styles.bulkPolicyToolbar}>
              <label className={styles.bulkPolicySearch}>
                <Search size={15} />
                <input
                  value={permissionSearchText}
                  placeholder={lang === "zh" ? "搜索可分配工具" : "Search assignable tools"}
                  onChange={(event) => setPermissionSearchText(event.target.value)}
                />
              </label>
              <div className={styles.bulkPolicyFilters}>
                {PERMISSION_FILTERS.map((filter) => (
                  <button
                    key={filter}
                    type="button"
                    className={filter === permissionFilter ? styles.filterButtonActive : styles.filterButton}
                    onClick={() => setPermissionFilter(filter)}
                  >
                    <span>{permissionFilterLabel(filter, lang)}</span>
                    <strong>{filter === "all" ? tools.length : policyModeCounts[filter]}</strong>
                  </button>
                ))}
              </div>
              <div className={styles.bulkPolicyActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!permissionTools.length}
                  onClick={selectVisiblePolicyTools}
                >
                  <ListChecks size={15} />
                  {lang === "zh" ? "选择当前结果" : "Select results"}
                </button>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!selectedPolicyCount}
                  onClick={() => setSelectedPolicyToolNames([])}
                >
                  <X size={15} />
                  {lang === "zh" ? "清空选择" : "Clear selection"}
                </button>
              </div>
            </div>
            <div className={styles.bulkPolicyActions}>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!selectedPolicyCount || toolPolicyMutation.isPending}
                onClick={() => setSelectedToolsPolicyMode("allowed")}
              >
                <CheckCircle2 size={15} />
                {lang === "zh" ? "选中设为允许" : "Allow selected"}
              </button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!selectedPolicyCount || toolPolicyMutation.isPending}
                onClick={() => setSelectedToolsPolicyMode("blocked")}
              >
                <CircleSlash size={15} />
                {lang === "zh" ? "选中设为禁用" : "Block selected"}
              </button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!selectedPolicyCount || toolPolicyMutation.isPending}
                onClick={() => setSelectedToolsPolicyMode("inherited")}
              >
                <RefreshCw size={15} />
                {lang === "zh" ? "选中设为默认" : "Default selected"}
              </button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!activePolicyAgent || !effectivePolicy.allowedTools.length || toolPolicyMutation.isPending}
                onClick={() => clearPolicyList("allowed")}
              >
                <X size={15} />
                {lang === "zh" ? "清空允许清单" : "Clear allow-list"}
              </button>
              <button
                type="button"
                className={styles.secondaryButton}
                disabled={!activePolicyAgent || !effectivePolicy.blockedTools.length || toolPolicyMutation.isPending}
                onClick={() => clearPolicyList("blocked")}
              >
                <X size={15} />
                {lang === "zh" ? "清空禁用清单" : "Clear block-list"}
              </button>
            </div>
            <div className={styles.bulkPolicyList}>
              {permissionTools.map((tool) => {
                const mode = toolPolicyMode(effectivePolicy, tool);
                const selected = selectedPolicyToolNameSet.has(tool.name);
                return (
                  <label
                    key={`policy-${tool.source}-${tool.id}`}
                    className={selected ? `${styles.bulkPolicyToolRow} ${styles.bulkPolicyToolRowSelected}` : styles.bulkPolicyToolRow}
                  >
                    <input
                      type="checkbox"
                      checked={selected}
                      onChange={() => togglePolicyToolSelection(tool.name)}
                    />
                    <span className={styles.bulkPolicyToolCopy}>
                      <strong>{tool.name}</strong>
                      <span>{tool.description || t("toolsNoDescription")}</span>
                    </span>
                    <span className={styles.toolBadges}>
                      <span className={`${styles.policyStatePill} ${styles[`policy_${mode}`]}`}>
                        {toolPolicyModeLabel(mode, lang)}
                      </span>
                      <span className={styles.sourcePill}>{displaySource(tool.source, lang)}</span>
                    </span>
                  </label>
                );
              })}
              {!permissionTools.length ? (
                <p className={styles.emptyState}>{lang === "zh" ? "没有匹配的工具权限项" : "No matching tool permission rows"}</p>
              ) : null}
            </div>
            <div className={styles.bulkPolicyFooter}>
              <span>
                {lang === "zh" ? "已选择" : "Selected"} <strong>{selectedPolicyCount}</strong> / {permissionTools.length}
              </span>
              <div className={styles.bulkPolicyActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!policyDirty || toolPolicyMutation.isPending}
                  onClick={resetPolicyDraft}
                >
                  <RotateCcw size={15} />
                  {lang === "zh" ? "放弃草稿" : "Discard draft"}
                </button>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={!policyDirty || !activePolicyAgent || toolPolicyMutation.isPending}
                  onClick={applyPolicyDraft}
                >
                  <Save size={15} />
                  {toolPolicyMutation.isPending ? (lang === "zh" ? "应用中" : "Applying") : (lang === "zh" ? "应用草稿" : "Apply draft")}
                </button>
              </div>
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
              <section className={styles.agentPolicyPanel}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{lang === "zh" ? "Agent 权限" : "Agent permissions"}</p>
                    <h3>{lang === "zh" ? "ToolPolicy" : "ToolPolicy"}</h3>
                  </div>
                  <span className={styles.countPill}>
                    {activePolicyAgent ? toolPolicyModeLabel(activePolicyMode, lang) : "-"}
                  </span>
                </div>
                <div className={styles.agentPolicyControls}>
                  <label className={styles.agentPolicySelect}>
                    <span>{lang === "zh" ? "Agent" : "Agent"}</span>
                    <select
                      value={activePolicyAgent?.agentId ?? ""}
                      disabled={!activeAgents.length || policyDirty || toolPolicyMutation.isPending}
                      onChange={(event) => setActivePolicyAgentId(event.target.value)}
                    >
                      {activeAgents.map((agent) => (
                        <option key={agent.agentId} value={agent.agentId}>
                          {agent.agentCode ? `${agent.agentCode} · ` : ""}{agent.displayName || agent.agentId}
                        </option>
                      ))}
                    </select>
                  </label>
                  <div className={styles.agentPolicyButtonGroup}>
                    <button
                      type="button"
                      className={activePolicyMode === "inherited" ? styles.policyModeButtonActive : styles.policyModeButton}
                      disabled={!activeTool || !activePolicyAgent || toolPolicyMutation.isPending}
                      onClick={() => updateActiveToolPolicy("inherited")}
                    >
                      {toolPolicyModeLabel("inherited", lang)}
                    </button>
                    <button
                      type="button"
                      className={activePolicyMode === "allowed" ? styles.policyModeButtonActive : styles.policyModeButton}
                      disabled={!activeTool || !activePolicyAgent || toolPolicyMutation.isPending}
                      onClick={() => updateActiveToolPolicy("allowed")}
                    >
                      {toolPolicyModeLabel("allowed", lang)}
                    </button>
                    <button
                      type="button"
                      className={activePolicyMode === "blocked" ? styles.policyModeButtonActive : styles.policyModeButton}
                      disabled={!activeTool || !activePolicyAgent || toolPolicyMutation.isPending}
                      onClick={() => updateActiveToolPolicy("blocked")}
                    >
                      {toolPolicyModeLabel("blocked", lang)}
                    </button>
                  </div>
                </div>
                <div className={styles.policyMeta}>
                  <span>
                    Agent: <strong>{activePolicyAgent ? `${activePolicyAgent.agentCode || ""} ${activePolicyAgent.displayName || activePolicyAgent.agentId}`.trim() : "-"}</strong>
                  </span>
                  <span>
                    allowed: <strong>{effectivePolicy.allowedTools.length}</strong>
                  </span>
                  <span>
                    blocked: <strong>{effectivePolicy.blockedTools.length}</strong>
                  </span>
                  <span>
                    policy: <strong>{effectivePolicy.policyId || activePolicyAgent?.toolPolicyId || "-"}</strong>
                  </span>
                </div>
                <p>{toolPolicyModeReason(activePolicyMode, lang)}</p>
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
                      <span>{image2ModelConfig?.selectedModel.model || image2ModelConfig?.fallbackModel.model || "-"}</span>
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
                  </div>
                  <p>
                    {lang === "zh"
                      ? "这里只选择设置页模型库中已经配置好的 image 模型；API Key、base_url 和 provider 仍在设置页维护。"
                      : "This only selects an already configured image model from Settings. API key, base_url, and provider stay in Settings."}
                  </p>
                  {image2ModelsQuery.isError ? (
                    <p className={styles.noticeError}>
                      {image2ModelsQuery.error instanceof Error ? image2ModelsQuery.error.message : String(image2ModelsQuery.error)}
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
                  disabled={!activeCanToggle || enableMutation.isPending}
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
                      deleteMutation.mutate(activeTool.id);
                    }
                  }}
                  title={activeTool.deleteAllowed ? undefined : activeTool.blockReason || t("toolsBuiltInProtected")}
                >
                  <Trash2 size={15} />
                  {deleteMutation.isPending ? t("deletingSelectedLogs") : t("deleteSelected")}
                </button>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!activeTool || !activePolicyAgent || policyDirty || testMutation.isPending}
                  title={policyDirty ? (lang === "zh" ? "先应用工具权限草稿再测试，避免用旧权限误判。" : "Apply the permission draft before testing to avoid stale policy results.") : undefined}
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
                  {testMutation.isPending ? t("toolsTesting") : t("toolsTest")}
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
              {testResult ? (
                <section className={styles.testPanel}>
                  <div className={styles.panelHeader}>
                    <div>
                      <p className={styles.panelEyebrow}>{t("toolsTestResult")}</p>
                      <h3>{testResult.status}</h3>
                    </div>
                    <span className={styles.countPill}>{agentTestLabel(testResult.agent, lang)}</span>
                  </div>
                  <p>{testResult.message}</p>
                  <div className={styles.policyMeta}>
                    <span>
                      {t("toolsAgentScope")}: <strong>{scopeLabel(testResult.agentScope, lang, t)}</strong>
                    </span>
                    <span>
                      ToolPolicy: <strong>{testResult.agent?.toolPolicyId || "-"}</strong>
                    </span>
                  </div>
                  <div className={styles.resultSummaryGrid}>
                    {testResultSummaryCards(testResult, t).map((card) => (
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
                        <h3>{testResult.agentCompatibility.status}</h3>
                      </div>
                      <span className={testResult.agentCompatibility.callable ? styles.countPill : styles.stateBadge}>
                        {testResult.agentCompatibility.callable ? t("yes") : t("no")}
                      </span>
                    </div>
                    <p>{testResult.agentCompatibility.message}</p>
                    <div className={styles.policyMeta}>
                      <span>
                        {t("toolsAgentMessageType")}:{" "}
                        <strong>{testResult.agentCompatibility.messageType || "-"}</strong>
                      </span>
                      <span>
                        {t("toolsAgentToolCall")}: <strong>{testResult.agentCompatibility.toolCall.name}</strong>
                      </span>
                    </div>
                    <pre>{jsonPreview(testResult.agentCompatibility.argsParsed)}</pre>
                  </section>
                  {testResult.resultPreview ? <pre>{testResult.resultPreview}</pre> : null}
                  <div className={styles.testArgs}>
                    <span>{t("toolsArgsUsed")}</span>
                    <pre>{jsonPreview(testResult.argsUsed)}</pre>
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
