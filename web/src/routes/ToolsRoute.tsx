import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ArrowLeft, CheckCircle2, CheckSquare, CircleSlash, FlaskConical, Power, RefreshCw, Search, Square, Trash2, Wrench } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type MouseEvent, type PointerEvent, useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

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
import { safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import { clampPaneWidth, keyboardPaneWidth, storedPaneWidth } from "./resizablePane";
import styles from "./ToolsRoute.module.css";

type ToolFilter = "all" | "built_in" | "generated" | "llm" | "enabled";
type ToolPolicyMode = "inherited" | "explicit_required" | "allowed" | "blocked" | "excluded";
type ToolBulkMutationResponse = {
  action: string;
  enabled?: boolean;
  successCount: number;
  skippedCount: number;
  failedCount: number;
  results: Array<{
    toolId: string;
    status: string;
    reason?: string;
  }>;
};
type ToolBundleGroup = {
  bundleId: string;
  label: string;
  description: string;
  tools: ToolRegistryItem[];
  highRiskToolCount: number;
  explicitAllowToolCount: number;
};
type AgentToolPolicyDraft = {
  allowedTools: string[];
  preferredTools: string[];
  blockedTools: string[];
  readScopes: string[];
  writeScopes: string[];
};
type ToolPolicyDraftMode = "inherited" | "allowed" | "blocked" | "excluded";
type ToolPermissionGroup = {
  bundleId: string;
  label: string;
  description: string;
  category: string;
  tools: ToolRegistryItem[];
  allowedCount: number;
  blockedCount: number;
  inheritedCount: number;
  highRiskCount: number;
};
type ScopedToolTestResult = {
  key: string;
  result: ToolTestResponse;
};
type ToolDeepLinkFocus = "policy" | "detail" | "bundle" | "test";
type Translate = (key: TranslationKey) => string;

const FILTERS: ToolFilter[] = ["all", "built_in", "generated", "llm", "enabled"];
const TOOLS_LEFT_PANEL_WIDTH_KEY = "vibelution.tools.left-panel-width";
const TOOLS_LEFT_PANEL_BOUNDS = { min: 260, max: 520 };
const TOOLS_LEFT_PANEL_DEFAULT_WIDTH = 350;
const MAIN_AGENT_SCOPE_ID = "main_agent";
const IMAGE2_TOOL_NAME = "image2_generate_tool";
const WEB_SEARCH_TOOL_NAME = "web_search_tool";

function normalizeToolDeepLinkFocus(value: string | null): ToolDeepLinkFocus {
  const normalized = String(value || "").trim().toLowerCase();
  if (normalized === "detail" || normalized === "bundle" || normalized === "test") {
    return normalized;
  }
  return "policy";
}

function toolMatchesDeepLink(tool: ToolRegistryItem, target: string) {
  const normalized = target.trim().toLowerCase();
  return Boolean(normalized) && [tool.id, tool.name].some((value) => String(value || "").toLowerCase() === normalized);
}

function agentMatchesDeepLink(agent: AgentInstance, target: string) {
  const normalized = target.trim().toLowerCase();
  return Boolean(normalized) && [agent.agentId, agent.agentCode].some((value) => String(value || "").toLowerCase() === normalized);
}

function sortedIds(values: string[]) {
  return Array.from(new Set(values.map((item) => String(item || "").trim()).filter(Boolean))).sort();
}

function sameStringSet(left: string[], right: string[]) {
  const leftSorted = sortedIds(left);
  const rightSorted = sortedIds(right);
  return leftSorted.length === rightSorted.length && leftSorted.every((value, index) => value === rightSorted[index]);
}

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

function normalizeToolPolicyDraftForAgent(
  draft: AgentToolPolicyDraft,
  _agent: AgentInstance | null | undefined,
): AgentToolPolicyDraft {
  const blocked = new Set(sortedIds(draft.blockedTools));
  const allowed = new Set(sortedIds(draft.allowedTools).filter((tool) => !blocked.has(tool)));
  const preferred = new Set(sortedIds(draft.preferredTools));
  const allowedTools = sortedIds(Array.from(allowed));
  const allowedSet = new Set(allowedTools);
  return {
    ...draft,
    allowedTools,
    preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowedSet.has(tool))),
    blockedTools: sortedIds(Array.from(blocked)),
    readScopes: sortedIds(draft.readScopes),
    writeScopes: sortedIds(draft.writeScopes),
  };
}

function toolPolicyDraftFromAgent(agent: AgentInstance | null | undefined): AgentToolPolicyDraft {
  return normalizeToolPolicyDraftForAgent({
    allowedTools: sortedIds(agent?.toolPolicy?.allowedTools ?? []),
    preferredTools: sortedIds(agent?.toolPolicy?.preferredTools ?? []),
    blockedTools: sortedIds(agent?.toolPolicy?.blockedTools ?? []),
    readScopes: sortedIds(agent?.toolPolicy?.readScopes ?? []),
    writeScopes: sortedIds(agent?.toolPolicy?.writeScopes ?? []),
  }, agent);
}

function toolPolicyDraftEqualsAgent(draft: AgentToolPolicyDraft, agent: AgentInstance | null | undefined) {
  const base = toolPolicyDraftFromAgent(agent);
  return (
    sameStringSet(draft.allowedTools, base.allowedTools)
    && sameStringSet(draft.preferredTools, base.preferredTools)
    && sameStringSet(draft.blockedTools, base.blockedTools)
    && sameStringSet(draft.readScopes, base.readScopes)
    && sameStringSet(draft.writeScopes, base.writeScopes)
  );
}

function toolPolicyForAgent(agent: AgentInstance | null | undefined): ToolPolicy {
  return agent?.toolPolicy ?? defaultToolPolicy(agent?.toolPolicyId || "default");
}

function policyDraftMode(draft: AgentToolPolicyDraft, toolName: string): ToolPolicyDraftMode {
  if (draft.blockedTools.includes(toolName)) {
    return "blocked";
  }
  if (draft.allowedTools.includes(toolName)) {
    return "allowed";
  }
  if (draft.allowedTools.length > 0) {
    return "excluded";
  }
  return "inherited";
}

function policyDraftModeLabel(mode: ToolPolicyDraftMode, lang: string) {
  const zh = {
    inherited: "未允许",
    allowed: "允许",
    blocked: "禁用",
    excluded: "未列入",
  };
  const en = {
    inherited: "Not allowed",
    allowed: "Allowed",
    blocked: "Blocked",
    excluded: "Excluded",
  };
  return (lang === "zh" ? zh : en)[mode];
}

function toolCategoryLabel(category: string, fallback: string | undefined, lang: string) {
  const normalized = String(category || "").trim();
  const zh: Record<string, string> = {
    workspace_read: "工作区读取",
    workspace_write: "工作区保存",
    code_quality: "代码质量",
    web_research: "网络与检索",
    git_evolution: "Git 与进化",
    task_runtime: "任务运行",
    agent_collaboration: "Agent 协作",
    memory_context: "记忆与上下文",
    self_model: "自我模型",
    media_research: "媒体与科研",
    custom_generated: "自定义工具",
    uncategorized: "未分类",
  };
  const en: Record<string, string> = {
    workspace_read: "Workspace read",
    workspace_write: "Workspace write",
    code_quality: "Code quality",
    web_research: "Web and research",
    git_evolution: "Git and evolution",
    task_runtime: "Task runtime",
    agent_collaboration: "Agent collaboration",
    memory_context: "Memory and context",
    self_model: "Self model",
    media_research: "Media and research",
    custom_generated: "Custom tools",
    uncategorized: "Uncategorized",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? fallback ?? normalized) || (lang === "zh" ? "未分类" : "Uncategorized");
}

function toolTierLabel(tier: string, lang: string) {
  const normalized = String(tier || "").trim();
  const zh: Record<string, string> = {
    low: "低风险",
    medium: "中风险",
    high: "高风险",
    generated: "自定义",
  };
  const en: Record<string, string> = {
    low: "Low risk",
    medium: "Medium risk",
    high: "High risk",
    generated: "Generated",
  };
  return ((lang === "zh" ? zh : en)[normalized] ?? normalized) || "-";
}

function toolBundleMeta(bundle: ToolBundle, lang: string) {
  const parts = [
    lang === "zh" ? `${bundle.toolCount} 个工具` : `${bundle.toolCount} tools`,
    lang === "zh" ? `${bundle.preferredToolCount} 个优先` : `${bundle.preferredToolCount} preferred`,
  ];
  if (bundle.highRiskToolCount > 0) {
    parts.push(lang === "zh" ? `${bundle.highRiskToolCount} 个高风险` : `${bundle.highRiskToolCount} high risk`);
  }
  if (bundle.explicitAllowToolCount > 0) {
    parts.push(lang === "zh" ? `${bundle.explicitAllowToolCount} 个需显式授权` : `${bundle.explicitAllowToolCount} explicit allow`);
  }
  return parts.join(" · ");
}

function groupPolicyToolsByBundle(
  tools: ToolRegistryItem[],
  bundles: ToolBundle[],
  draft: AgentToolPolicyDraft,
  lang: string,
): ToolPermissionGroup[] {
  const toolByName = new Map(tools.map((tool) => [tool.name, tool]));
  const groups: ToolPermissionGroup[] = [];
  const pushedToolKeys = new Set<string>();
  const pushTool = (group: ToolPermissionGroup, tool: ToolRegistryItem) => {
    const mode = policyDraftMode(draft, tool.name);
    group.tools.push(tool);
    if (mode === "allowed") {
      group.allowedCount += 1;
    } else if (mode === "blocked") {
      group.blockedCount += 1;
    } else {
      group.inheritedCount += 1;
    }
    if (tool.permissionTier === "high" || tool.permissionPolicy?.requiresExplicitAllow) {
      group.highRiskCount += 1;
    }
  };

  for (const bundle of bundles) {
    const group: ToolPermissionGroup = {
      bundleId: bundle.bundleId,
      label: bundle.label,
      description: bundle.description,
      category: bundle.category,
      tools: [],
      allowedCount: 0,
      blockedCount: 0,
      inheritedCount: 0,
      highRiskCount: 0,
    };
    for (const toolName of bundle.toolNames) {
      const tool = toolByName.get(toolName);
      if (!tool) {
        continue;
      }
      pushedToolKeys.add(tool.name);
      pushTool(group, tool);
    }
    if (group.tools.length) {
      groups.push(group);
    }
  }

  const unbundled: ToolPermissionGroup = {
    bundleId: "unbundled",
    label: lang === "zh" ? "未归入工具包" : "Unbundled tools",
    description: lang === "zh" ? "这些工具暂未归入任何工具包，建议单独审查后再授权。" : "Tools not yet assigned to a package. Review them individually before allowing them.",
    category: "unbundled",
    tools: [],
    allowedCount: 0,
    blockedCount: 0,
    inheritedCount: 0,
    highRiskCount: 0,
  };
  for (const tool of tools) {
    if (!pushedToolKeys.has(tool.name)) {
      pushTool(unbundled, tool);
    }
  }
  if (unbundled.tools.length) {
    groups.push(unbundled);
  }

  return groups.sort((left, right) => {
    const leftTouched = left.allowedCount + left.blockedCount;
    const rightTouched = right.allowedCount + right.blockedCount;
    if (leftTouched !== rightTouched) {
      return rightTouched - leftTouched;
    }
    return left.label.localeCompare(right.label);
  });
}

function buildAgentCapabilityPreview(draft: AgentToolPolicyDraft, tools: ToolRegistryItem[], lang: string) {
  const allowed = new Set(draft.allowedTools);
  const blocked = new Set(draft.blockedTools);
  const inherited = Math.max(0, tools.length - allowed.size - blocked.size);
  const effectiveAllowed = allowed.size;
  const highRiskAllowed = tools.filter((tool) => allowed.has(tool.name) && (tool.permissionTier === "high" || tool.permissionPolicy?.requiresExplicitAllow)).length;
  const explicitAllowed = tools.filter((tool) => allowed.has(tool.name) && tool.permissionPolicy?.requiresExplicitAllow).length;
  return {
    effectiveAllowed,
    preferred: draft.preferredTools.length,
    blocked: draft.blockedTools.length,
    inherited,
    highRiskAllowed,
    explicitAllowed,
    writeBoundaryLabel: draft.writeScopes.includes("shared")
      ? lang === "zh" ? "私人与共享" : "Private and shared"
      : lang === "zh" ? "仅私人" : "Private only",
  };
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
    inherited: "未允许",
    explicit_required: "需显式授权",
    allowed: "允许清单",
    blocked: "禁用",
    excluded: "未在允许清单",
  };
  const en = {
    inherited: "Not allowed",
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

function toolRegistryCountsForTools(tools: ToolRegistryItem[], currentCounts: ToolRegistryPayload["counts"]) {
  return {
    ...currentCounts,
    total: tools.length,
    builtIn: tools.filter((tool) => tool.source === "built_in").length,
    generated: tools.filter((tool) => tool.source === "generated").length,
    llmVisible: tools.filter((tool) => tool.llmVisible).length,
    runtimeActive: tools.filter((tool) => tool.runtimeActive).length,
    enabledGenerated: tools.filter((tool) => tool.source === "generated" && tool.enabled).length,
    invalidGenerated: tools.filter((tool) => tool.source === "generated" && tool.status === "invalid").length,
  };
}

function toolRegistryPayloadWithTools(payload: ToolRegistryPayload, tools: ToolRegistryItem[]): ToolRegistryPayload {
  return {
    ...payload,
    tools,
    counts: toolRegistryCountsForTools(tools, payload.counts),
  };
}

function updatedToolRegistryPayload(
  payload: ToolRegistryPayload | undefined,
  toolId: string,
  updater: (tool: ToolRegistryItem) => ToolRegistryItem,
): ToolRegistryPayload | undefined {
  if (!payload) {
    return payload;
  }
  let updated = false;
  const tools = payload.tools.map((tool) => {
    if (tool.id !== toolId) {
      return tool;
    }
    updated = true;
    return updater(tool);
  });
  return updated ? toolRegistryPayloadWithTools(payload, tools) : payload;
}

function removedToolRegistryPayload(payload: ToolRegistryPayload | undefined, toolId: string): ToolRegistryPayload | undefined {
  if (!payload) {
    return payload;
  }
  const tools = payload.tools.filter((tool) => tool.id !== toolId);
  return tools.length === payload.tools.length ? payload : toolRegistryPayloadWithTools(payload, tools);
}

function optimisticToolEnabled(tool: ToolRegistryItem, enabled: boolean): ToolRegistryItem {
  return {
    ...tool,
    enabled,
    runtimeActive: enabled ? tool.runtimeActive : false,
    llmVisible: enabled ? tool.llmVisible : false,
    updatedAt: new Date().toISOString(),
  };
}

export function ToolsRoute() {
  const { lang, t } = useAppI18n();
  const [searchParams] = useSearchParams();
  const bulkCopy = useMemo(() => toolsBulkCopy(lang), [lang]);
  const queryClient = useQueryClient();
  const [activeFilter, setActiveFilter] = useState<ToolFilter>("all");
  const [searchText, setSearchText] = useState("");
  const [toolPolicySearchText, setToolPolicySearchText] = useState("");
  const [activeAgentScopeId, setActiveAgentScopeId] = useState(MAIN_AGENT_SCOPE_ID);
  const [activePolicyAgentId, setActivePolicyAgentId] = useState("");
  const [toolPolicyDraft, setToolPolicyDraft] = useState<AgentToolPolicyDraft>(() => toolPolicyDraftFromAgent(null));
  const [activeToolId, setActiveToolId] = useState<string | null>(null);
  const [selectedBundleId, setSelectedBundleId] = useState("");
  const [leftPanelWidth, setLeftPanelWidth] = useState(() =>
    storedPaneWidth(TOOLS_LEFT_PANEL_WIDTH_KEY, TOOLS_LEFT_PANEL_DEFAULT_WIDTH, TOOLS_LEFT_PANEL_BOUNDS),
  );
  const [leftPanelCollapsed, setLeftPanelCollapsed] = useState(false);
  const [selectedToolIds, setSelectedToolIds] = useState<Set<string>>(() => new Set());
  const [bulkSelectionAnchorToolId, setBulkSelectionAnchorToolId] = useState<string | null>(null);
  const [bulkToolPending, setBulkToolPending] = useState(false);
  const [notice, setNotice] = useState<{ tone: "neutral" | "success" | "error"; text: string }>({
    tone: "neutral",
    text: "",
  });
  const [testResult, setTestResult] = useState<ScopedToolTestResult | null>(null);
  const pageVisible = usePageVisibility();
  const requestedAgentId = useMemo(() => String(searchParams.get("agent") || "").trim(), [searchParams]);
  const requestedScopeId = useMemo(() => String(searchParams.get("scope") || "").trim(), [searchParams]);
  const requestedToolKey = useMemo(() => String(searchParams.get("tool") || searchParams.get("toolId") || "").trim(), [searchParams]);
  const requestedBundleId = useMemo(() => String(searchParams.get("bundle") || searchParams.get("bundleId") || "").trim(), [searchParams]);
  const requestedFocus = useMemo(() => normalizeToolDeepLinkFocus(searchParams.get("focus")), [searchParams]);
  const returnToPath = useMemo(() => safeAgentCenterReturnToPath(searchParams.get("returnTo")), [searchParams]);
  const returnToLabel = useMemo(() => {
    const normalized = String(searchParams.get("returnLabel") || "").trim();
    if (normalized === "agents") {
      return lang === "zh" ? "返回 Agent 配置" : "Back to Agent config";
    }
    return lang === "zh" ? "返回来源页" : "Back";
  }, [lang, searchParams]);

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
  const deepLinkTargetTool = useMemo(
    () => requestedToolKey ? tools.find((tool) => toolMatchesDeepLink(tool, requestedToolKey)) ?? null : null,
    [requestedToolKey, tools],
  );
  const deepLinkTargetBundle = useMemo(
    () => requestedBundleId ? toolBundles.find((bundle) => bundle.bundleId === requestedBundleId) ?? null : null,
    [requestedBundleId, toolBundles],
  );
  const defaultSelectedBundle = useMemo(
    () => toolBundles.find((bundle) => bundle.toolCount > 0) ?? toolBundles[0] ?? null,
    [toolBundles],
  );
  const selectedBundle = useMemo(
    () => toolBundles.find((bundle) => bundle.bundleId === selectedBundleId) ?? deepLinkTargetBundle ?? defaultSelectedBundle,
    [deepLinkTargetBundle, defaultSelectedBundle, selectedBundleId, toolBundles],
  );
  const activeTool = tools.find((tool) => tool.id === activeToolId) ?? deepLinkTargetTool ?? visibleTools[0] ?? null;
  const activeToolBundleLabels = activeTool ? bundleLabelsForTool(activeTool, toolBundles, lang) : [];
  const activeScopeState = activeTool ? scopeStateForTool(activeTool, activeAgentScope.id) : null;

  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
    staleTime: 30_000,
    refetchInterval: false,
    refetchIntervalInBackground: false,
  });
  const activeAgents = useMemo(
    () => (agentsQuery.data ?? []).filter((agent) => agent.status !== "archived"),
    [agentsQuery.data],
  );
  const deepLinkTargetAgent = useMemo(
    () => requestedAgentId ? activeAgents.find((agent) => agentMatchesDeepLink(agent, requestedAgentId)) ?? null : null,
    [activeAgents, requestedAgentId],
  );
  const activePolicyAgent = activeAgents.find((agent) => agent.agentId === activePolicyAgentId) ?? activeAgents[0] ?? null;
  const activePolicy = toolPolicyForAgent(activePolicyAgent);
  const activePolicyMode = activeTool && activePolicyAgent ? toolPolicyMode(activePolicy, activeTool) : "inherited";
  const editablePolicyTools = useMemo(() => {
    const query = toolPolicySearchText.trim().toLowerCase();
    return tools.filter((tool) => {
      if (!tool.llmVisible && !tool.runtimeActive) {
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
        tool.permissionTier,
        ...(tool.bundleIds ?? []),
        ...(tool.capabilityTags ?? []),
        ...(tool.riskTags ?? []),
      ].join(" ").toLowerCase().includes(query);
    });
  }, [toolPolicySearchText, tools]);
  const editablePolicyGroups = useMemo(
    () => groupPolicyToolsByBundle(editablePolicyTools, toolBundles, toolPolicyDraft, lang),
    [editablePolicyTools, lang, toolBundles, toolPolicyDraft],
  );
  const toolPolicyDirty = !toolPolicyDraftEqualsAgent(toolPolicyDraft, activePolicyAgent);
  const capabilityPreview = useMemo(
    () => buildAgentCapabilityPreview(toolPolicyDraft, editablePolicyTools, lang),
    [editablePolicyTools, lang, toolPolicyDraft],
  );
  const scopedTools = useMemo(
    () => tools.filter((tool) => scopeStateForTool(tool, activeAgentScopeId).visible),
    [activeAgentScopeId, tools],
  );
  const filterCounts = useMemo(() => toolFilterCounts(scopedTools), [scopedTools]);

  useEffect(() => {
    if (deepLinkTargetTool && activeToolId !== deepLinkTargetTool.id) {
      setActiveToolId(deepLinkTargetTool.id);
      setActiveFilter("all");
      return;
    }
    if (!activeToolId || !tools.some((tool) => tool.id === activeToolId)) {
      setActiveToolId(visibleTools[0]?.id ?? null);
    }
  }, [activeToolId, deepLinkTargetTool, tools, visibleTools]);

  useEffect(() => {
    if (requestedScopeId && agentScopes.some((scope) => scope.id === requestedScopeId) && activeAgentScopeId !== requestedScopeId) {
      setActiveAgentScopeId(requestedScopeId);
      return;
    }
    if (!agentScopes.length || agentScopes.some((scope) => scope.id === activeAgentScopeId)) {
      return;
    }
    setActiveAgentScopeId(MAIN_AGENT_SCOPE_ID);
  }, [activeAgentScopeId, agentScopes, requestedScopeId]);

  useEffect(() => {
    if (!activeAgents.length) {
      setActivePolicyAgentId("");
      return;
    }
    if (deepLinkTargetAgent && activePolicyAgentId !== deepLinkTargetAgent.agentId) {
      setActivePolicyAgentId(deepLinkTargetAgent.agentId);
      return;
    }
    if (!activePolicyAgentId || !activeAgents.some((agent) => agent.agentId === activePolicyAgentId)) {
      setActivePolicyAgentId(activeAgents[0].agentId);
    }
  }, [activeAgents, activePolicyAgentId, deepLinkTargetAgent]);

  useEffect(() => {
    setToolPolicyDraft(toolPolicyDraftFromAgent(activePolicyAgent));
  }, [activePolicyAgent?.agentId, activePolicyAgent?.toolPolicy]);

  useEffect(() => {
    if (requestedToolKey && deepLinkTargetTool?.id === activeToolId) {
      return;
    }
    if (activeToolId && !visibleTools.some((tool) => tool.id === activeToolId)) {
      setActiveToolId(visibleTools[0]?.id ?? null);
    }
  }, [activeToolId, deepLinkTargetTool?.id, requestedToolKey, visibleTools]);

  useEffect(() => {
    if (deepLinkTargetBundle && selectedBundleId !== deepLinkTargetBundle.bundleId) {
      setSelectedBundleId(deepLinkTargetBundle.bundleId);
      return;
    }
    if (!selectedBundleId || !toolBundles.some((bundle) => bundle.bundleId === selectedBundleId)) {
      setSelectedBundleId(defaultSelectedBundle?.bundleId ?? "");
    }
  }, [deepLinkTargetBundle, defaultSelectedBundle, selectedBundleId, toolBundles]);

  useEffect(() => {
    if (!requestedToolKey && !requestedBundleId && requestedFocus === "policy") {
      return;
    }
    const targetId = requestedFocus === "detail" || requestedFocus === "test"
      ? "agent-tools-detail"
      : requestedFocus === "bundle"
        ? "agent-tools-bundles"
        : "agent-tools-policy";
    window.requestAnimationFrame(() => {
      document.getElementById(targetId)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
    });
  }, [requestedBundleId, requestedFocus, requestedToolKey]);

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
    onMutate: async (payload) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.tools() });
      const previousTools = queryClient.getQueryData<ToolRegistryPayload>(queryKeys.tools());
      queryClient.setQueryData<ToolRegistryPayload | undefined>(
        queryKeys.tools(),
        (current) => updatedToolRegistryPayload(
          current,
          payload.toolId,
          (tool) => optimisticToolEnabled(tool, payload.enabled),
        ),
      );
      return { previousTools };
    },
    onSuccess: (tool) => {
      queryClient.setQueryData<ToolRegistryPayload | undefined>(
        queryKeys.tools(),
        (current) => updatedToolRegistryPayload(current, tool.id, () => tool),
      );
      setNotice({
        tone: "success",
        text: tool.enabled
          ? lang === "zh" ? `已启用 ${tool.name}` : `Enabled ${tool.name}`
          : lang === "zh" ? `已停用 ${tool.name}` : `Disabled ${tool.name}`,
      });
      refresh();
    },
    onError: (error, _variables, context) => {
      if (context?.previousTools) {
        queryClient.setQueryData(queryKeys.tools(), context.previousTools);
      }
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      refresh();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (toolId: string) =>
      fetchJson<GeneratedToolDeleteResponse>(`/api/tools/${encodeURIComponent(toolId)}`, {
        method: "DELETE",
      }),
    onMutate: async (toolId) => {
      await queryClient.cancelQueries({ queryKey: queryKeys.tools() });
      const previousTools = queryClient.getQueryData<ToolRegistryPayload>(queryKeys.tools());
      const previousActiveToolId = activeToolId;
      const previousSelectedToolIds = new Set(selectedToolIds);
      queryClient.setQueryData<ToolRegistryPayload | undefined>(
        queryKeys.tools(),
        (current) => removedToolRegistryPayload(current, toolId),
      );
      if (toolId === activeToolId) {
        setActiveToolId(null);
      }
      setSelectedToolIds((current) => {
        const next = new Set(current);
        next.delete(toolId);
        return next;
      });
      return { previousTools, previousActiveToolId, previousSelectedToolIds };
    },
    onSuccess: (payload) => {
      queryClient.setQueryData<ToolRegistryPayload | undefined>(
        queryKeys.tools(),
        (current) => removedToolRegistryPayload(current, payload.toolId),
      );
      setNotice({ tone: "success", text: payload.summary });
      refresh();
    },
    onError: (error, _toolId, context) => {
      if (context?.previousTools) {
        queryClient.setQueryData(queryKeys.tools(), context.previousTools);
      }
      if (context) {
        setActiveToolId(context.previousActiveToolId);
        setSelectedToolIds(new Set(context.previousSelectedToolIds));
      }
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
      refresh();
    },
  });

  const updateToolPolicyMutation = useMutation({
    mutationFn: (payload: { agentId: string; draft: AgentToolPolicyDraft; basePolicy: ToolPolicy | undefined }) =>
      fetchJson<AgentInstance>(`/api/agents/${encodeURIComponent(payload.agentId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          toolPolicy: {
            ...defaultToolPolicy(payload.basePolicy?.policyId || "default"),
            ...(payload.basePolicy ?? {}),
            allowedTools: sortedIds(payload.draft.allowedTools),
            preferredTools: sortedIds(payload.draft.preferredTools),
            blockedTools: sortedIds(payload.draft.blockedTools),
            readScopes: sortedIds(payload.draft.readScopes),
            writeScopes: sortedIds(payload.draft.writeScopes),
          },
        }),
      }),
    onSuccess: (agent) => {
      queryClient.setQueryData<AgentInstance[] | undefined>(
        queryKeys.agents(),
        (current) => current?.map((item) => item.agentId === agent.agentId ? { ...item, ...agent } : item),
      );
      setToolPolicyDraft(toolPolicyDraftFromAgent(agent));
      setNotice({
        tone: "success",
        text: lang === "zh"
          ? `已保存 ${agent.displayName || agent.agentId} 的工具能力`
          : `Saved tool permissions for ${agent.displayName || agent.agentId}`,
      });
      void queryClient.invalidateQueries({ queryKey: queryKeys.agents() });
      void queryClient.invalidateQueries({ queryKey: queryKeys.tools() });
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
  const activePolicyAgentPending = updateToolPolicyMutation.isPending && updateToolPolicyMutation.variables?.agentId === activePolicyAgent?.agentId;
  const activeCanDelete = Boolean(activeTool?.deleteAllowed) && !activeToolDeletePending;
  const activeCanToggle = Boolean(activeIsGenerated && activeTool?.validated && activeTool.status === "validated");
  const activeIsImage2Tool = activeTool?.name === IMAGE2_TOOL_NAME;
  const activeIsWebSearchTool = activeTool?.name === WEB_SEARCH_TOOL_NAME;
  const deepLinkNotice = useMemo(() => {
    if (requestedAgentId && !agentsQuery.isPending && !deepLinkTargetAgent) {
      return lang === "zh"
        ? `未找到深链指定的 Agent：${requestedAgentId}，已回退到可配置 Agent。`
        : `Deep-linked Agent was not found: ${requestedAgentId}. Fell back to an available Agent.`;
    }
    if (requestedToolKey && !toolsQuery.isPending && !deepLinkTargetTool) {
      return lang === "zh"
        ? `未找到深链指定的工具：${requestedToolKey}，已显示当前可见工具。`
        : `Deep-linked tool was not found: ${requestedToolKey}. Showing the current visible tool.`;
    }
    if (requestedBundleId && !toolsQuery.isPending && !deepLinkTargetBundle) {
      return lang === "zh"
        ? `未找到深链指定的工具包：${requestedBundleId}，已使用默认工具包。`
        : `Deep-linked tool package was not found: ${requestedBundleId}. Using the default package.`;
    }
    return "";
  }, [
    activeAgents,
    agentsQuery.isPending,
    deepLinkTargetAgent,
    deepLinkTargetBundle,
    deepLinkTargetTool,
    lang,
    requestedAgentId,
    requestedBundleId,
    requestedToolKey,
    toolsQuery.isPending,
  ]);
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

  function updateToolPolicyMode(toolName: string, mode: Exclude<ToolPolicyDraftMode, "excluded">) {
    setToolPolicyDraft((current) => {
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      if (mode === "allowed") {
        allowed.add(toolName);
        blocked.delete(toolName);
      } else if (mode === "blocked") {
        allowed.delete(toolName);
        preferred.delete(toolName);
        blocked.add(toolName);
      } else {
        allowed.delete(toolName);
        preferred.delete(toolName);
        blocked.delete(toolName);
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
        blockedTools: sortedIds(Array.from(blocked)),
      }, activePolicyAgent);
    });
  }

  function toggleToolPolicyScope(field: "readScopes" | "writeScopes", scope: string, selected: boolean) {
    setToolPolicyDraft((current) => {
      const scopes = new Set(current[field]);
      if (selected) {
        scopes.add(scope);
      } else {
        scopes.delete(scope);
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        [field]: sortedIds(Array.from(scopes)),
      }, activePolicyAgent);
    });
  }

  function applyToolBundle(bundle: ToolBundle, mode: "merge" | "replace") {
    setToolPolicyDraft((current) => {
      const bundleTools = sortedIds(bundle.toolNames ?? []);
      const bundlePreferred = sortedIds((bundle.preferredToolNames ?? []).filter((tool) => bundleTools.includes(tool)));
      if (mode === "replace") {
        return normalizeToolPolicyDraftForAgent({
          ...current,
          allowedTools: bundleTools,
          preferredTools: bundlePreferred,
          blockedTools: [],
        }, activePolicyAgent);
      }
      const allowed = new Set(current.allowedTools);
      const preferred = new Set(current.preferredTools);
      const blocked = new Set(current.blockedTools);
      for (const tool of bundleTools) {
        if (!blocked.has(tool)) {
          allowed.add(tool);
        }
      }
      for (const tool of bundlePreferred) {
        if (!blocked.has(tool)) {
          preferred.add(tool);
        }
      }
      return normalizeToolPolicyDraftForAgent({
        ...current,
        allowedTools: sortedIds(Array.from(allowed)),
        preferredTools: sortedIds(Array.from(preferred).filter((tool) => allowed.has(tool))),
        blockedTools: sortedIds(Array.from(blocked)),
      }, activePolicyAgent);
    });
  }

  function saveToolPolicy() {
    if (!activePolicyAgent || !toolPolicyDirty || activePolicyAgentPending) {
      return;
    }
    const saveDraft = normalizeToolPolicyDraftForAgent(toolPolicyDraft, activePolicyAgent);
    updateToolPolicyMutation.mutate({
      agentId: activePolicyAgent.agentId,
      draft: saveDraft,
      basePolicy: activePolicyAgent.toolPolicy,
    });
  }

  function toggleBulkTool(toolId: string, selected: boolean, extendRange = false) {
    setSelectedToolIds((current) => {
      const next = new Set(current);
      if (extendRange && bulkSelectionAnchorToolId) {
        const ids = visibleTools.map((tool) => tool.id);
        const anchorIndex = ids.indexOf(bulkSelectionAnchorToolId);
        const targetIndex = ids.indexOf(toolId);
        if (anchorIndex >= 0 && targetIndex >= 0) {
          const [start, end] = anchorIndex < targetIndex ? [anchorIndex, targetIndex] : [targetIndex, anchorIndex];
          for (const id of ids.slice(start, end + 1)) {
            next.add(id);
          }
          return next;
        }
      }
      if (selected) {
        next.add(toolId);
      } else {
        next.delete(toolId);
      }
      return next;
    });
    setBulkSelectionAnchorToolId(toolId);
  }

  function handleToolRowClick(tool: ToolRegistryItem, event: MouseEvent<HTMLButtonElement>) {
    if (event.ctrlKey || event.metaKey || event.shiftKey) {
      event.preventDefault();
      toggleBulkTool(tool.id, event.shiftKey ? true : !selectedToolIds.has(tool.id), event.shiftKey);
      return;
    }
    setActiveToolId(tool.id);
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
    const skippedLocal = selectedTools.filter((tool) => !canBulkToggleTool(tool));
    try {
      const payload = await fetchJson<ToolBulkMutationResponse>("/api/tools/generated/bulk-enabled", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          toolIds: selectedTools.filter(canBulkToggleTool).map((tool) => tool.id),
          enabled,
        }),
      });
      const notes = [
        ...skippedLocal.map((tool) => `${tool.name}: ${bulkCopy.skippedToggle}`),
        ...payload.results
          .filter((item) => item.status === "failed" || item.status === "skipped")
          .map((item) => `${item.toolId}: ${item.reason || item.status}`),
      ];
      setNotice({
        tone: payload.failedCount > 0 ? "error" : "success",
        text: toolsBulkActionSummary(
          enabled ? bulkCopy.enableResult : bulkCopy.disableResult,
          payload.successCount,
          payload.skippedCount + skippedLocal.length,
          payload.failedCount,
          notes,
          lang,
        ),
      });
      clearBulkTools();
      refresh();
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBulkToolPending(false);
    }
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
    let deletedActiveTool = false;
    const skippedLocal = selectedTools.filter((tool) => !tool.deleteAllowed);
    try {
      const payload = await fetchJson<ToolBulkMutationResponse>("/api/tools/bulk-delete", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ toolIds: selectedTools.filter((tool) => tool.deleteAllowed).map((tool) => tool.id) }),
      });
      deletedActiveTool = payload.results.some((item) => item.status === "deleted" && item.toolId === activeToolId);
      if (deletedActiveTool) {
        setActiveToolId(null);
      }
      const notes = [
        ...skippedLocal.map((tool) => `${tool.name}: ${bulkCopy.skippedDelete}`),
        ...payload.results
          .filter((item) => item.status === "failed" || item.status === "skipped")
          .map((item) => `${item.toolId}: ${item.reason || item.status}`),
      ];
      setNotice({
        tone: payload.failedCount > 0 ? "error" : "success",
        text: toolsBulkActionSummary(
          bulkCopy.deleteResult,
          payload.successCount,
          payload.skippedCount + skippedLocal.length,
          payload.failedCount,
          notes,
          lang,
        ),
      });
      clearBulkTools();
      refresh();
    } catch (error) {
      setNotice({ tone: "error", text: error instanceof Error ? error.message : String(error) });
    } finally {
      setBulkToolPending(false);
    }
  }

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div title={t("toolsPageSubtitle")}>
          <p className={styles.eyebrow}>{t("navTools")}</p>
          <h1 className={styles.title}>{t("toolsPageTitle")}</h1>
        </div>
        {returnToPath ? (
          <Link className={styles.returnButton} to={returnToPath} title={returnToLabel}>
            <ArrowLeft size={15} />
            <span>{returnToLabel}</span>
          </Link>
        ) : null}
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
          <p className={styles.panelEyebrow}>{lang === "zh" ? "配置 Agent" : "Configure Agent"}</p>
          <strong>{activePolicyAgent ? `${activePolicyAgent.agentCode || ""} ${activePolicyAgent.displayName || activePolicyAgent.agentId}`.trim() : "-"}</strong>
          <span>{toolPolicyDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}</span>
        </div>
        <label className={styles.scopeSelect}>
          <span>{lang === "zh" ? "配置" : "Agent"}</span>
          <select
            value={activePolicyAgent?.agentId ?? ""}
            disabled={!activeAgents.length}
            aria-label={lang === "zh" ? "配置 Agent" : "Configure Agent"}
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
        <label className={styles.scopeSelect}>
          <span>{t("toolsAgentScope")}</span>
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
        {deepLinkNotice ? <p className={styles.deepLinkNotice}>{deepLinkNotice}</p> : null}
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
              <section key={group.bundleId} className={styles.toolBundleGroup} title={group.description || group.label}>
                <header className={styles.toolBundleHeader}>
                  <div>
                    <strong>{group.label}</strong>
                    <span>{group.tools.length} {lang === "zh" ? "个工具" : "tools"}</span>
                  </div>
                  <small>
                    {lang === "zh" ? "高风险" : "High risk"} {group.highRiskToolCount} · {lang === "zh" ? "显式授权" : "Explicit"} {group.explicitAllowToolCount}
                  </small>
                </header>
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
                            onChange={(event) => toggleBulkTool(
                              tool.id,
                              event.target.checked,
                              Boolean((event.nativeEvent as globalThis.MouseEvent).shiftKey),
                            )}
                          />
                          {bulkSelected ? <CheckSquare size={15} /> : <Square size={15} />}
                        </label>
                        <button
                          type="button"
                          className={isActive ? styles.toolButtonActive : styles.toolButton}
                          onClick={(event) => handleToolRowClick(tool, event)}
                        >
                          <span className={`${styles.statusDot} ${styles[`status_${statusTone(tool)}`]}`} />
                          <span className={styles.toolCopy}>
                            <strong>{tool.name}</strong>
                            <span title={tool.description || t("toolsNoDescription")}>
                            {toolCategoryLabel(tool.category, tool.categoryLabel, lang)} · {toolTierLabel(tool.permissionTier, lang)}
                          </span>
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
          <section
            id="agent-tools-policy"
            className={`${styles.agentPermissionSummaryPanel} ${requestedFocus === "policy" ? styles.deepLinkFocus : ""}`}
          >
            <div className={styles.panelHeader}>
              <div>
                <p className={styles.panelEyebrow}>{lang === "zh" ? "Agent 工具配置" : "Agent tool configuration"}</p>
                <h2>{activePolicyAgent ? `${activePolicyAgent.agentCode || ""} ${activePolicyAgent.displayName || activePolicyAgent.agentId}`.trim() : "-"}</h2>
              </div>
              <span className={toolPolicyDirty ? styles.stateBadge : styles.countPill}>
                {toolPolicyDirty ? (lang === "zh" ? "未保存" : "Unsaved") : (lang === "zh" ? "已同步" : "Synced")}
              </span>
            </div>
            <div className={styles.permissionSummaryGrid}>
              <div className={styles.permissionSummaryCards}>
                <span>{lang === "zh" ? "允许" : "Allowed"} <strong>{toolPolicyDraft.allowedTools.length}</strong></span>
                <span>{lang === "zh" ? "优先" : "Preferred"} <strong>{toolPolicyDraft.preferredTools.length}</strong></span>
                <span>{lang === "zh" ? "禁用" : "Blocked"} <strong>{toolPolicyDraft.blockedTools.length}</strong></span>
                <span>{lang === "zh" ? "未允许" : "Not allowed"} <strong>{capabilityPreview.inherited}</strong></span>
                <span>{lang === "zh" ? "高风险允许" : "High-risk allowed"} <strong>{capabilityPreview.highRiskAllowed}</strong></span>
              </div>
            </div>
            <section className={styles.policyDraftPanel}>
              <div className={styles.policyDraftSummary}>
                <strong>{lang === "zh" ? "实际能力预览" : "Effective capability preview"}</strong>
                <span>{lang === "zh" ? "实际允许" : "Effective allowed"}: {capabilityPreview.effectiveAllowed}</span>
                <span>{lang === "zh" ? "需显式授权" : "Explicit grants"}: {capabilityPreview.explicitAllowed}</span>
                <span>{lang === "zh" ? "写入边界" : "Write boundary"}: {capabilityPreview.writeBoundaryLabel}</span>
              </div>
              <div className={styles.workspaceScopePanel}>
                <span>{lang === "zh" ? "工作空间写入" : "Workspace write"}</span>
                <label>
                  <input type="checkbox" checked disabled />
                  {lang === "zh" ? "私人工作区" : "Private workspace"}
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={toolPolicyDraft.writeScopes.includes("shared")}
                    onChange={(event) => toggleToolPolicyScope("writeScopes", "shared", event.target.checked)}
                  />
                  {lang === "zh" ? "共享资料区" : "Shared workspace"}
                </label>
              </div>
              {toolBundles.length ? (
                <div
                  id="agent-tools-bundles"
                  className={`${styles.toolBundleApplyBar} ${requestedFocus === "bundle" ? styles.deepLinkFocus : ""}`}
                >
                  <label className={styles.toolBundleSelect}>
                    <span>{lang === "zh" ? "工具包" : "Package"}</span>
                    <select
                      value={selectedBundle?.bundleId ?? ""}
                      onChange={(event) => setSelectedBundleId(event.target.value)}
                    >
                      {toolBundles.map((bundle) => (
                        <option key={bundle.bundleId} value={bundle.bundleId}>
                          {bundle.label}
                        </option>
                      ))}
                    </select>
                  </label>
                  <span className={styles.toolBundleSummary} title={selectedBundle?.description || ""}>
                    {selectedBundle ? toolBundleMeta(selectedBundle, lang) : "-"}
                  </span>
                  <div className={styles.toolBundleApplyActions}>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={!selectedBundle}
                      onClick={() => selectedBundle && applyToolBundle(selectedBundle, "merge")}
                    >
                      {lang === "zh" ? "追加" : "Add"}
                    </button>
                    <button
                      type="button"
                      className={styles.secondaryButton}
                      disabled={!selectedBundle}
                      onClick={() => selectedBundle && applyToolBundle(selectedBundle, "replace")}
                    >
                      {lang === "zh" ? "替换" : "Replace"}
                    </button>
                  </div>
                </div>
              ) : null}
              <label className={styles.searchBox}>
                <Search size={15} />
                <input
                  value={toolPolicySearchText}
                  placeholder={lang === "zh" ? "搜索可分配工具" : "Search assignable tools"}
                  onChange={(event) => setToolPolicySearchText(event.target.value)}
                />
              </label>
              {editablePolicyTools.length ? (
                <div className={styles.toolPermissionList}>
                  {editablePolicyGroups.map((group) => (
                    <section key={group.bundleId} className={styles.toolPermissionGroup}>
                      <header className={styles.toolPermissionGroupHeader}>
                        <div>
                          <strong>{group.label}</strong>
                          <span>
                            {group.tools.length} tools · {lang === "zh" ? "允许" : "Allowed"} {group.allowedCount} · {lang === "zh" ? "禁用" : "Blocked"} {group.blockedCount} · {lang === "zh" ? "未允许" : "Not allowed"} {group.inheritedCount}
                          </span>
                        </div>
                        {group.highRiskCount ? <small>{lang === "zh" ? "高风险" : "High risk"} {group.highRiskCount}</small> : null}
                      </header>
                      <div className={styles.toolPermissionGroupList}>
                        {group.tools.map((tool) => {
                          const mode = policyDraftMode(toolPolicyDraft, tool.name);
                          const tags = [...(tool.capabilityTags ?? []), ...(tool.riskTags ?? [])].slice(0, 4);
                          return (
                            <div key={`${tool.source}:${tool.id}`} className={styles.toolPermissionRow}>
                              <span>
                                <strong>{tool.name}</strong>
                                <small title={tool.description || tool.source}>{displaySource(tool.source, lang)}</small>
                                <span className={styles.toolPermissionMeta}>
                                  <em>{toolTierLabel(tool.permissionTier, lang)}</em>
                                  <small>{toolCategoryLabel(tool.category, tool.categoryLabel, lang)}</small>
                                  {tags.length ? <small>{tags.join(" / ")}</small> : null}
                                </span>
                              </span>
                              <div className={styles.segmentedControl} aria-label={tool.name}>
                                <button
                                  type="button"
                                  className={mode === "inherited" || mode === "excluded" ? styles.segmentActive : styles.segmentButton}
                                  onClick={() => updateToolPolicyMode(tool.name, "inherited")}
                                >
                                  {policyDraftModeLabel(mode === "excluded" ? "excluded" : "inherited", lang)}
                                </button>
                                <button
                                  type="button"
                                  className={mode === "allowed" ? styles.segmentActive : styles.segmentButton}
                                  onClick={() => updateToolPolicyMode(tool.name, "allowed")}
                                >
                                  {policyDraftModeLabel("allowed", lang)}
                                </button>
                                <button
                                  type="button"
                                  className={mode === "blocked" ? styles.segmentActiveDanger : styles.segmentButton}
                                  onClick={() => updateToolPolicyMode(tool.name, "blocked")}
                                >
                                  {policyDraftModeLabel("blocked", lang)}
                                </button>
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </section>
                  ))}
                </div>
              ) : (
                <p className={styles.emptyState}>{lang === "zh" ? "当前没有可分配工具。" : "No assignable tools."}</p>
              )}
              <div className={styles.detailActions}>
                <button
                  type="button"
                  className={styles.secondaryButton}
                  disabled={!toolPolicyDirty || activePolicyAgentPending}
                  onClick={() => setToolPolicyDraft(toolPolicyDraftFromAgent(activePolicyAgent))}
                >
                  {lang === "zh" ? "重置草稿" : "Reset draft"}
                </button>
                <button
                  type="button"
                  className={styles.primaryButton}
                  disabled={!activePolicyAgent || !toolPolicyDirty || activePolicyAgentPending}
                  onClick={saveToolPolicy}
                >
                  {activePolicyAgentPending ? (lang === "zh" ? "保存中..." : "Saving...") : (lang === "zh" ? "保存工具配置" : "Save tool config")}
                </button>
              </div>
            </section>
          </section>
          {activeTool ? (
            <aside
              id="agent-tools-detail"
              className={`${styles.toolDetailPanel} ${requestedFocus === "detail" || requestedFocus === "test" ? styles.deepLinkFocus : ""}`}
            >
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
                <span className={styles.policyHint}>
                  {lang === "zh" ? "工具测试使用该 Agent 已保存的 ToolPolicy。" : "Tool tests use this Agent's saved ToolPolicy."}
                </span>
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
            </aside>
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
