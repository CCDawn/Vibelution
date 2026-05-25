import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, CircleSlash, FlaskConical, Power, RefreshCw, Search, Trash2, Wrench } from "lucide-react";
import { type CSSProperties, type KeyboardEvent, type PointerEvent, useEffect, useMemo, useState } from "react";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import {
  GeneratedToolDeleteResponse,
  ToolAgentScopeState,
  ToolAgentScopeSummary,
  ToolRegistryItem,
  ToolRegistryPayload,
  ToolTestResponse,
} from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { PaneCollapseHandle } from "../components/layout/PaneCollapseHandle";
import type { TranslationKey } from "../i18n/dictionary";
import { useAppI18n } from "../i18n/useAppI18n";
import { clampPaneWidth, keyboardPaneWidth, storedPaneWidth } from "./resizablePane";
import styles from "./ToolsRoute.module.css";

type ToolFilter = "all" | "built_in" | "generated" | "llm" | "enabled";
type Translate = (key: TranslationKey) => string;

const FILTERS: ToolFilter[] = ["all", "built_in", "generated", "llm", "enabled"];
const TOOLS_LEFT_PANEL_WIDTH_KEY = "vibelution.tools.left-panel-width";
const TOOLS_LEFT_PANEL_BOUNDS = { min: 260, max: 520 };
const TOOLS_LEFT_PANEL_DEFAULT_WIDTH = 350;
const MAIN_AGENT_SCOPE_ID = "main_agent";

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

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.tools() });
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
  }, [activeAgentScopeId, activeToolId]);

  useEffect(() => {
    if (!agentScopes.length || agentScopes.some((scope) => scope.id === activeAgentScopeId)) {
      return;
    }
    setActiveAgentScopeId(MAIN_AGENT_SCOPE_ID);
  }, [activeAgentScopeId, agentScopes]);

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
    mutationFn: (payload: { toolId: string; agentScopeId: string }) =>
      fetchJson<ToolTestResponse>(`/api/tools/${encodeURIComponent(payload.toolId)}/test`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ args: {}, agentScope: payload.agentScopeId }),
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

  const counts = toolsQuery.data?.counts;
  const activeIsGenerated = activeTool?.source === "generated";
  const activeCanDelete = Boolean(activeTool?.deleteAllowed) && !deleteMutation.isPending;
  const activeCanToggle = Boolean(activeIsGenerated && activeTool?.validated && activeTool.status === "validated");
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
                  <span className={styles.sourcePill}>{displaySource(tool.source, lang)}</span>
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
                  disabled={!activeTool || testMutation.isPending}
                  onClick={() => {
                    if (activeTool) {
                      testMutation.mutate({ toolId: activeTool.id, agentScopeId: activeAgentScope.id });
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
                    <span className={styles.countPill}>{scopeLabel(testResult.agentScope, lang, t)}</span>
                  </div>
                  <p>{testResult.message}</p>
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
