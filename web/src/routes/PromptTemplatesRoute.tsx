import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Archive, ArrowLeft, CheckCircle2, CheckSquare, FileText, RefreshCw, RotateCcw, Save, Search, Square, SquarePen, Tags } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { AgentInstance, PromptTemplate, PromptTemplateWorkspace } from "../api/types";
import { VButton, VIconButton, VNativeInput, VNativeSelect, VNativeTextarea, VRouteHeader } from "../components/vui";
import { useShellI18n } from "../i18n/useShellI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import { safeAgentCenterReturnToPath } from "./agentCenterRoutes";
import styles from "./PromptTemplatesRoute.styles";

type PromptCategoryFilter = "all" | "chat" | "research" | "supervised_evolution" | "self_evolution" | "general";

type PromptEditorState = {
  templateId: string;
  name: string;
  category: string;
  content: string;
};

const CATEGORY_FILTERS: PromptCategoryFilter[] = [
  "all",
  "chat",
  "research",
  "supervised_evolution",
  "self_evolution",
  "general",
];


function copyFor(lang: string) {
  return lang === "zh"
    ? {
        eyebrow: "Agent 提示词",
        title: "Prompt Templates",
        subtitle: "统一管理所有长期 Agent 可绑定的系统提示词模板，科研、聊天、监督进化和自进化都在这里。",
        refresh: "刷新",
        search: "搜索模板、分类、路径或引用 Agent",
        templates: "模板",
        linkedAgents: "引用 Agent",
        editor: "提示词编辑器",
        bulkSelected: "已选",
        bulkSelectVisible: "选择当前列表",
        bulkClear: "清空",
        bulkCategory: "批量分类",
        bulkApplyCategory: "改分类",
        bulkReset: "批量恢复默认",
        bulkDeactivate: "批量停用",
        bulkWorking: "批量处理中...",
        bulkNoSelection: "请先选择提示词模板。",
        bulkCategoryResult: "批量分类更新完成",
        bulkResetResult: "批量恢复默认完成",
        bulkDeactivateResult: "批量停用完成",
        bulkSkippedNoDefault: "没有默认内容，跳过",
        bulkResetConfirm: "确认把已选提示词模板恢复为默认内容？没有默认内容的模板会跳过。",
        bulkDeactivateConfirm: "确认批量停用已选提示词模板？已绑定的 Agent 可能需要重新分配模板。",
        emptyList: "没有匹配的提示词模板。",
        emptyEditor: "选择一个提示词模板后在这里编辑。",
        loading: "加载中...",
        loadFailed: "读取失败",
        save: "保存模板",
        saving: "保存中",
        saved: "提示词模板已保存。",
        reset: "恢复默认",
        resetDone: "已恢复默认模板。",
        resetUnavailable: "没有默认内容",
        category: "分类",
        source: "源文件",
        sourceExists: "源文件存在",
        status: "状态",
        usage: "引用数",
        hash: "内容哈希",
        content: "提示词内容",
        defaultPreview: "默认内容预览",
        noAgents: "暂无 Agent 引用这个模板。",
        yes: "是",
        no: "否",
        all: "全部",
        returnToAgents: "返回 Agent 配置",
      }
    : {
        eyebrow: "Agent prompts",
        title: "Prompt Templates",
        subtitle: "Manage every prompt template that long-lived Agents can bind to across chat, research, supervised evolution, and self-evolution.",
        refresh: "Refresh",
        search: "Search templates, categories, paths, or linked Agents",
        templates: "Templates",
        linkedAgents: "Linked Agents",
        editor: "Prompt editor",
        bulkSelected: "Selected",
        bulkSelectVisible: "Select visible",
        bulkClear: "Clear",
        bulkCategory: "Bulk category",
        bulkApplyCategory: "Set category",
        bulkReset: "Bulk reset",
        bulkDeactivate: "Bulk deactivate",
        bulkWorking: "Working...",
        bulkNoSelection: "Select prompt templates first.",
        bulkCategoryResult: "Bulk category update finished",
        bulkResetResult: "Bulk reset finished",
        bulkDeactivateResult: "Bulk deactivate finished",
        bulkSkippedNoDefault: "No default content; skipped",
        bulkResetConfirm: "Restore selected prompt templates to their default content? Templates without defaults will be skipped.",
        bulkDeactivateConfirm: "Deactivate selected prompt templates? Linked Agents may need a replacement template.",
        emptyList: "No matching prompt templates.",
        emptyEditor: "Select a prompt template to edit it here.",
        loading: "Loading...",
        loadFailed: "Load failed",
        save: "Save template",
        saving: "Saving",
        saved: "Prompt template saved.",
        reset: "Restore default",
        resetDone: "Default template restored.",
        resetUnavailable: "No default content",
        category: "Category",
        source: "Source",
        sourceExists: "Source exists",
        status: "Status",
        usage: "Usage",
        hash: "Content hash",
        content: "Prompt content",
        defaultPreview: "Default preview",
        noAgents: "No Agents reference this template.",
        yes: "Yes",
        no: "No",
        all: "All",
        returnToAgents: "Back to Agent config",
      };
}

function categoryLabel(category: string, lang: string) {
  const labels: Record<string, { zh: string; en: string }> = {
    all: { zh: "全部", en: "All" },
    chat: { zh: "聊天", en: "Chat" },
    research: { zh: "科研", en: "Research" },
    supervised_evolution: { zh: "监督进化", en: "Supervised" },
    self_evolution: { zh: "自进化", en: "Self-evolution" },
    general: { zh: "通用", en: "General" },
  };
  const item = labels[category];
  return item ? item[lang === "zh" ? "zh" : "en"] : category || labels.general[lang === "zh" ? "zh" : "en"];
}

function templateSearchText(template: PromptTemplate, linkedAgents: AgentInstance[]) {
  return [
    template.promptTemplateId,
    template.templateId,
    template.name,
    template.category,
    template.sourcePath,
    template.status,
    template.contentHash,
    ...linkedAgents.flatMap((agent) => [agent.agentId, agent.agentCode, agent.displayName, agent.roleKey, agent.primaryMode]),
  ].join(" ").toLowerCase();
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error || "");
}

function clip(value: string, max = 420) {
  const text = String(value || "").trim();
  return text.length > max ? `${text.slice(0, max)}...` : text;
}

function editorFromTemplate(template: PromptTemplate): PromptEditorState {
  return {
    templateId: template.promptTemplateId,
    name: template.name,
    category: template.category,
    content: template.content ?? "",
  };
}

function promptBulkActionSummary(action: string, success: number, skipped: number, failed: number, notes: string[], lang: string) {
  const parts = lang === "zh"
    ? [`成功 ${success}`, `跳过 ${skipped}`, `失败 ${failed}`]
    : [`success ${success}`, `skipped ${skipped}`, `failed ${failed}`];
  const preview = notes.slice(0, 3).join("；");
  return preview ? `${action}: ${parts.join(" / ")}。${preview}` : `${action}: ${parts.join(" / ")}`;
}

export function PromptTemplatesRoute() {
  const { lang } = useShellI18n();
  const copy = useMemo(() => copyFor(lang), [lang]);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialCategory = (searchParams.get("category") || "all") as PromptCategoryFilter;
  const linkedAgentId = String(searchParams.get("agent") || "").trim();
  const linkedTemplateId = String(searchParams.get("template") || "").trim();
  const focusTarget = String(searchParams.get("focus") || "").trim();
  const returnToPath = safeAgentCenterReturnToPath(searchParams.get("returnTo"));
  const [categoryFilter, setCategoryFilter] = useState<PromptCategoryFilter>(
    CATEGORY_FILTERS.includes(initialCategory) ? initialCategory : "all",
  );
  const [searchText, setSearchText] = useState("");
  const [activeTemplateId, setActiveTemplateId] = useState("");
  const [editor, setEditor] = useState<PromptEditorState | null>(null);
  const [notice, setNotice] = useState("");
  const [selectedTemplateIds, setSelectedTemplateIds] = useState<Set<string>>(() => new Set());
  const [bulkCategory, setBulkCategory] = useState("general");
  const [bulkPromptPending, setBulkPromptPending] = useState(false);

  const templatesQuery = useQuery({
    queryKey: queryKeys.promptTemplates(),
    queryFn: () => fetchJson<PromptTemplateWorkspace>("/api/prompt-templates"),
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents?detail=summary"),
  });
  const templates = templatesQuery.data?.templates ?? [];
  const agents = agentsQuery.data ?? [];
  const agentsByTemplate = useMemo(() => {
    const map = new Map<string, AgentInstance[]>();
    for (const agent of agents) {
      const key = String(agent.promptTemplateId || "").trim();
      if (!key) {
        continue;
      }
      map.set(key, [...(map.get(key) ?? []), agent]);
    }
    return map;
  }, [agents]);
  const filteredTemplates = useMemo(() => {
    const term = searchText.trim().toLowerCase();
    return templates.filter((template) => {
      if (categoryFilter !== "all" && template.category !== categoryFilter) {
        return false;
      }
      return !term || templateSearchText(template, agentsByTemplate.get(template.promptTemplateId) ?? []).includes(term);
    });
  }, [agentsByTemplate, categoryFilter, searchText, templates]);
  const selectedTemplates = useMemo(
    () => filteredTemplates.filter((template) => selectedTemplateIds.has(template.promptTemplateId)),
    [filteredTemplates, selectedTemplateIds],
  );
  const allVisibleTemplatesSelected = filteredTemplates.length > 0 && selectedTemplates.length === filteredTemplates.length;

  useEffect(() => {
    const nextCategory = (searchParams.get("category") || "all") as PromptCategoryFilter;
    const normalizedCategory = CATEGORY_FILTERS.includes(nextCategory) ? nextCategory : "all";
    setCategoryFilter((current) => (current === normalizedCategory ? current : normalizedCategory));
  }, [searchParams]);

  useEffect(() => {
    const requestedTemplateId = linkedTemplateId || (
      linkedAgentId
        ? String(agents.find((agent) => agent.agentId === linkedAgentId)?.promptTemplateId || "").trim()
        : ""
    );
    if (!requestedTemplateId || searchParams.get("category")) {
      return;
    }
    const requestedTemplate = templates.find((template) => template.promptTemplateId === requestedTemplateId);
    const requestedCategory = requestedTemplate?.category as PromptCategoryFilter | undefined;
    if (requestedCategory && CATEGORY_FILTERS.includes(requestedCategory) && requestedCategory !== categoryFilter) {
      setCategoryFilter(requestedCategory);
    }
  }, [agents, categoryFilter, linkedAgentId, linkedTemplateId, searchParams, templates]);

  useEffect(() => {
    if (categoryFilter === "all" && !searchParams.has("category")) {
      return;
    }
    if (categoryFilter !== "all" && searchParams.get("category") === categoryFilter) {
      return;
    }
    setSearchParams((current) => {
      const next = new URLSearchParams(current);
      if (categoryFilter === "all") {
        next.delete("category");
      } else {
        next.set("category", categoryFilter);
      }
      return next;
    }, { replace: true });
  }, [categoryFilter, searchParams, setSearchParams]);

  useEffect(() => {
    const requestedTemplateId = linkedTemplateId || (
      linkedAgentId
        ? String(agents.find((agent) => agent.agentId === linkedAgentId)?.promptTemplateId || "").trim()
        : ""
    );
    if (requestedTemplateId && filteredTemplates.some((template) => template.promptTemplateId === requestedTemplateId)) {
      setActiveTemplateId((current) => (current === requestedTemplateId ? current : requestedTemplateId));
      return;
    }
    if (activeTemplateId && filteredTemplates.some((template) => template.promptTemplateId === activeTemplateId)) {
      return;
    }
    setActiveTemplateId(filteredTemplates[0]?.promptTemplateId ?? "");
  }, [activeTemplateId, agents, filteredTemplates, linkedAgentId, linkedTemplateId]);

  useEffect(() => {
    setSelectedTemplateIds((current) => {
      const visibleIds = new Set(filteredTemplates.map((template) => template.promptTemplateId));
      const next = new Set(Array.from(current).filter((templateId) => visibleIds.has(templateId)));
      return next.size === current.size ? current : next;
    });
  }, [filteredTemplates]);

  const activeTemplate = templates.find((template) => template.promptTemplateId === activeTemplateId) ?? null;
  const activeAgents = activeTemplate ? agentsByTemplate.get(activeTemplate.promptTemplateId) ?? [] : [];
  const detailQuery = useQuery({
    queryKey: ["prompt-templates", activeTemplateId, "detail"] as const,
    queryFn: () => fetchJson<PromptTemplate>(`/api/prompt-templates/${encodeURIComponent(activeTemplateId)}`),
    enabled: Boolean(activeTemplateId),
  });

  useEffect(() => {
    if (detailQuery.data) {
      setEditor(editorFromTemplate(detailQuery.data));
    } else if (activeTemplate) {
      setEditor(editorFromTemplate(activeTemplate));
    } else {
      setEditor(null);
    }
  }, [activeTemplate, detailQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (payload: PromptEditorState) =>
      fetchJson<PromptTemplate>(`/api/prompt-templates/${encodeURIComponent(payload.templateId)}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          name: payload.name,
          content: payload.content,
        }),
      }),
    onSuccess: async (template) => {
      if (activeTemplateId === template.promptTemplateId) {
        setEditor(editorFromTemplate(template));
      }
      setNotice(copy.saved);
      await queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates() });
      await queryClient.invalidateQueries({ queryKey: ["prompt-templates", template.promptTemplateId, "detail"] });
    },
  });
  const resetMutation = useMutation({
    mutationFn: (templateId: string) =>
      fetchJson<PromptTemplate>(`/api/prompt-templates/${encodeURIComponent(templateId)}/reset`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
      }),
    onSuccess: async (template) => {
      if (activeTemplateId === template.promptTemplateId) {
        setEditor(editorFromTemplate(template));
      }
      setNotice(copy.resetDone);
      await queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates() });
      await queryClient.invalidateQueries({ queryKey: ["prompt-templates", template.promptTemplateId, "detail"] });
    },
  });
  const savePending = saveMutation.isPending && saveMutation.variables?.templateId === activeTemplateId;
  const resetPending = resetMutation.isPending && resetMutation.variables === activeTemplateId;
  const busy = savePending || resetPending || detailQuery.isFetching;
  const editableTemplate = detailQuery.data ?? activeTemplate;
  const hasDefault = Boolean(editableTemplate?.defaultContent?.trim());
  const categoriesInUse = new Set(templates.map((template) => template.category || "general"));
  const visibleFilters = CATEGORY_FILTERS.filter((filter) => filter === "all" || filter === "general" || categoriesInUse.has(filter));

  function selectCategory(filter: PromptCategoryFilter) {
    setCategoryFilter(filter);
    setNotice("");
  }

  function toggleTemplateSelection(templateId: string, selected: boolean) {
    setSelectedTemplateIds((current) => {
      const next = new Set(current);
      if (selected) {
        next.add(templateId);
      } else {
        next.delete(templateId);
      }
      return next;
    });
  }

  function selectVisibleTemplates() {
    setSelectedTemplateIds(new Set(filteredTemplates.map((template) => template.promptTemplateId)));
  }

  function clearSelectedTemplates() {
    setSelectedTemplateIds(new Set());
  }

  async function bulkPatchTemplates(patch: Partial<Pick<PromptTemplate, "category" | "status">>, actionLabel: string) {
    if (bulkPromptPending) {
      return;
    }
    if (!selectedTemplates.length) {
      setNotice(copy.bulkNoSelection);
      return;
    }
    if (patch.status === "inactive") {
      const confirmed = window.confirm(copy.bulkDeactivateConfirm);
      if (!confirmed) {
        return;
      }
    }
    setBulkPromptPending(true);
    let success = 0;
    let failed = 0;
    const notes: string[] = [];
    for (const template of selectedTemplates) {
      try {
        await fetchJson<PromptTemplate>(`/api/prompt-templates/${encodeURIComponent(template.promptTemplateId)}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(patch),
        });
        success += 1;
      } catch (error) {
        failed += 1;
        notes.push(`${template.name || template.promptTemplateId}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    setBulkPromptPending(false);
    setNotice(promptBulkActionSummary(actionLabel, success, 0, failed, notes, lang));
    clearSelectedTemplates();
    await queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates() });
    if (activeTemplateId) {
      await queryClient.invalidateQueries({ queryKey: ["prompt-templates", activeTemplateId, "detail"] });
    }
  }

  async function bulkResetTemplates() {
    if (bulkPromptPending) {
      return;
    }
    if (!selectedTemplates.length) {
      setNotice(copy.bulkNoSelection);
      return;
    }
    const confirmed = window.confirm(copy.bulkResetConfirm);
    if (!confirmed) {
      return;
    }
    setBulkPromptPending(true);
    let success = 0;
    let skipped = 0;
    let failed = 0;
    const notes: string[] = [];
    for (const template of selectedTemplates) {
      if (!template.defaultContent?.trim()) {
        skipped += 1;
        notes.push(`${template.name || template.promptTemplateId}: ${copy.bulkSkippedNoDefault}`);
        continue;
      }
      try {
        await fetchJson<PromptTemplate>(`/api/prompt-templates/${encodeURIComponent(template.promptTemplateId)}/reset`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
        });
        success += 1;
      } catch (error) {
        failed += 1;
        notes.push(`${template.name || template.promptTemplateId}: ${error instanceof Error ? error.message : String(error)}`);
      }
    }
    setBulkPromptPending(false);
    setNotice(promptBulkActionSummary(copy.bulkResetResult, success, skipped, failed, notes, lang));
    clearSelectedTemplates();
    await queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates() });
    if (activeTemplateId) {
      await queryClient.invalidateQueries({ queryKey: ["prompt-templates", activeTemplateId, "detail"] });
    }
  }

  return (
    <section className={styles.routeClass}>
      <VRouteHeader
        className={styles.headerClass}
        eyebrow={copy.eyebrow}
        title={copy.title}
        meta={copy.subtitle}
        actions={(
          <div className={styles.headerActionsClass}>
            {returnToPath ? (
              <Link className={styles.returnButtonClass} to={returnToPath} title={copy.returnToAgents}>
                <ArrowLeft size={15} />
                <span>{copy.returnToAgents}</span>
              </Link>
            ) : null}
            <VIconButton
              type="button"
              className={styles.refreshButtonClass}
              label={copy.refresh}
              icon={<RefreshCw size={15} />}
              isDisabled={templatesQuery.isFetching}
              onPress={() => templatesQuery.refetch()}
            />
          </div>
        )}
      />

      <div className={styles.controlStripClass}>
        <AgentManagementNav active="prompts" className={styles.managementNavClass} />

        <div className={styles.summaryGridClass}>
          <section className={styles.summaryCardClass}>
            <span className={styles.summaryLabelClass}>{copy.templates}</span>
            <strong className={styles.summaryValueClass}>{templates.length}</strong>
          </section>
          <section className={styles.summaryCardClass}>
            <span className={styles.summaryLabelClass}>{copy.linkedAgents}</span>
            <strong className={styles.summaryValueClass}>{agents.filter((agent) => agent.promptTemplateId).length}</strong>
          </section>
          <section className={styles.summaryCardClass}>
            <span className={styles.summaryLabelClass}>{copy.category}</span>
            <strong className={styles.summaryValueClass}>{visibleFilters.length - 1}</strong>
          </section>
          <section className={styles.summaryCardClass}>
            <span className={styles.summaryLabelClass}>{copy.source}</span>
            <strong className={styles.summaryValueClass}>{templatesQuery.data?.storagePath ?? templatesQuery.data?.path ?? "-"}</strong>
          </section>
        </div>
      </div>

      <main className={styles.workspaceClass}>
        <aside className={styles.listPanelClass}>
          <div className={styles.panelHeaderClass}>
            <div>
              <p className={styles.panelEyebrowClass}>{copy.templates}</p>
              <h2 className={styles.panelTitleClass}>{filteredTemplates.length} / {templates.length}</h2>
            </div>
            <FileText size={17} />
          </div>

          <label className={styles.searchBoxClass}>
            <Search size={14} />
            <VNativeInput className={styles.searchInputClass} value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={copy.search} />
          </label>

          <div className={styles.filterRowClass}>
            {visibleFilters.map((filter) => (
              <VButton
                key={filter}
                type="button"
                className={categoryFilter === filter ? styles.filterButtonActiveClass : styles.filterButtonClass}
                onPress={() => selectCategory(filter)}
              >
                {filter === "all" ? copy.all : categoryLabel(filter, lang)}
              </VButton>
            ))}
          </div>

          <section className={styles.bulkActionBarClass} aria-label={copy.bulkSelected}>
            <div className={styles.bulkSummaryClass}>
              <CheckSquare size={15} />
              <strong className={styles.bulkSummaryTitleClass}>{copy.bulkSelected}</strong>
              <span>{selectedTemplates.length} / {filteredTemplates.length}</span>
            </div>
            <VButton
              type="button"
              className={styles.secondaryButtonClass}
              icon={allVisibleTemplatesSelected ? <Square size={14} /> : <CheckSquare size={14} />}
              isDisabled={!filteredTemplates.length || bulkPromptPending}
              onPress={allVisibleTemplatesSelected ? clearSelectedTemplates : selectVisibleTemplates}
            >
              {allVisibleTemplatesSelected ? copy.bulkClear : copy.bulkSelectVisible}
            </VButton>
            <label className={styles.bulkSelectFieldClass}>
              <Tags size={14} />
              <span>{copy.bulkCategory}</span>
              <VNativeSelect className={styles.bulkSelectClass} value={bulkCategory} disabled={bulkPromptPending} onChange={(event) => setBulkCategory(event.target.value)}>
                {CATEGORY_FILTERS.filter((filter) => filter !== "all").map((filter) => (
                  <option key={filter} value={filter}>
                    {categoryLabel(filter, lang)}
                  </option>
                ))}
              </VNativeSelect>
            </label>
            <VButton
              type="button"
              className={styles.primaryButtonClass}
              icon={<CheckCircle2 size={14} />}
              isDisabled={!selectedTemplates.length || bulkPromptPending}
              onPress={() => bulkPatchTemplates({ category: bulkCategory }, copy.bulkCategoryResult)}
            >
              {bulkPromptPending ? copy.bulkWorking : copy.bulkApplyCategory}
            </VButton>
            <VButton
              type="button"
              className={styles.secondaryButtonClass}
              icon={<RotateCcw size={14} />}
              isDisabled={!selectedTemplates.length || bulkPromptPending}
              onPress={bulkResetTemplates}
            >
              {bulkPromptPending ? copy.bulkWorking : copy.bulkReset}
            </VButton>
            <VButton
              type="button"
              className={styles.secondaryButtonClass}
              icon={<Archive size={14} />}
              isDisabled={!selectedTemplates.length || bulkPromptPending}
              onPress={() => bulkPatchTemplates({ status: "inactive" }, copy.bulkDeactivateResult)}
            >
              {bulkPromptPending ? copy.bulkWorking : copy.bulkDeactivate}
            </VButton>
          </section>

          <div className={styles.templateListClass}>
            {templatesQuery.isError ? (
              <p className={styles.emptyStateClass}>{copy.loadFailed}</p>
            ) : templatesQuery.isPending ? (
              <p className={styles.emptyStateClass}>{copy.loading}</p>
            ) : filteredTemplates.length === 0 ? (
              <p className={styles.emptyStateClass}>{copy.emptyList}</p>
            ) : (
              filteredTemplates.map((template) => {
                const linkedCount = agentsByTemplate.get(template.promptTemplateId)?.length ?? 0;
                const selected = selectedTemplateIds.has(template.promptTemplateId);
                const linkedTarget = linkedTemplateId === template.promptTemplateId
                  || Boolean(linkedAgentId && agentsByTemplate.get(template.promptTemplateId)?.some((agent) => agent.agentId === linkedAgentId));
                return (
                  <div key={template.promptTemplateId} className={`${styles.selectableRowClass} ${linkedTarget ? styles.selectableRowLinkedClass : ""}`}>
                    <label className={`${styles.rowSelectClass} ${linkedTarget ? styles.linkedBorderClass : ""}`} title={`${copy.bulkSelected}: ${template.name || template.promptTemplateId}`}>
                      <VNativeInput
                        className={styles.hiddenCheckboxClass}
                        type="checkbox"
                        checked={selected}
                        aria-label={`${copy.bulkSelected}: ${template.name || template.promptTemplateId}`}
                        onChange={(event) => toggleTemplateSelection(template.promptTemplateId, event.target.checked)}
                      />
                      {selected ? <CheckSquare size={15} /> : <Square size={15} />}
                    </label>
                    <VButton
                      type="button"
                      className={[
                        styles.templateButtonBaseClass,
                        activeTemplateId === template.promptTemplateId ? styles.templateButtonActiveClass : "",
                        linkedTarget ? styles.linkedBorderClass : "",
                      ].filter(Boolean).join(" ")}
                      onPress={() => {
                        setActiveTemplateId(template.promptTemplateId);
                        setNotice("");
                      }}
                    >
                      <span className={styles.templateMainClass}>
                        <strong>{template.name || template.promptTemplateId}</strong>
                        <span>{template.promptTemplateId}</span>
                      </span>
                      <span className={styles.templateMetaClass}>
                        <span className={styles.categoryPillClass}>{categoryLabel(template.category, lang)}</span>
                        <span>{copy.usage}: {linkedCount}</span>
                        <span>{template.sourcePath || "-"}</span>
                      </span>
                    </VButton>
                  </div>
                );
              })
            )}
          </div>
        </aside>

        <section className={`${styles.editorPanelClass} ${focusTarget === "editor" ? styles.editorPanelFocusedClass : ""}`}>
          {editor && editableTemplate ? (
            <>
              <div className={styles.editorHeaderClass}>
                <div>
                  <p className={styles.panelEyebrowClass}>{copy.editor}</p>
                  <h2 className={styles.panelTitleClass}>{editableTemplate.promptTemplateId}</h2>
                  <p className={styles.panelDescriptionClass}>{editableTemplate.sourcePath || editableTemplate.category}</p>
                </div>
                <SquarePen size={18} />
              </div>

              <div className={styles.editorMetaClass}>
                <section className={styles.detailRowClass}>
                  <span className={styles.detailLabelClass}>{copy.category}</span>
                  <strong className={styles.detailValueClass}>{categoryLabel(editor.category, lang)}</strong>
                </section>
                <section className={styles.detailRowClass}>
                  <span className={styles.detailLabelClass}>{copy.sourceExists}</span>
                  <strong className={styles.detailValueClass}>{editableTemplate.sourceExists ? copy.yes : copy.no}</strong>
                </section>
                <section className={styles.detailRowClass}>
                  <span className={styles.detailLabelClass}>{copy.status}</span>
                  <strong className={styles.detailValueClass}>{editableTemplate.status || "active"}</strong>
                </section>
              </div>

              <label className={`${styles.fieldClass} ${styles.nameFieldClass}`}>
                <span className={styles.fieldLabelClass}>{copy.templates}</span>
                <VNativeInput className={styles.fieldInputClass} value={editor.name} onChange={(event) => setEditor({ ...editor, name: event.target.value })} />
              </label>

              <label className={`${styles.fieldClass} ${styles.contentFieldClass}`}>
                <span className={styles.fieldLabelClass}>{copy.content}</span>
                <VNativeTextarea className={styles.contentTextareaClass} value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} />
              </label>

              <div className={styles.bottomGridClass}>
                <section className={styles.detailCardClass}>
                  <div className={styles.contentHeaderClass}>
                    <h3 className={styles.cardTitleClass}>{copy.defaultPreview}</h3>
                    <span className={hasDefault ? styles.statePillClass : styles.templateMetaClass}>{hasDefault ? copy.yes : copy.no}</span>
                  </div>
                  <p className={styles.detailCardHelperClass}>{clip(editableTemplate.defaultContent || copy.resetUnavailable)}</p>
                  <section className={styles.detailRowClass}>
                    <span className={styles.detailLabelClass}>{copy.hash}</span>
                    <strong className={styles.detailValueClass}>{editableTemplate.contentHash || "-"}</strong>
                  </section>
                </section>

                <section className={styles.agentListClass}>
                  <h3 className={styles.cardTitleClass}>{copy.linkedAgents}</h3>
                  <div className={styles.agentRowsClass}>
                    {activeAgents.length ? (
                      activeAgents.map((agent) => (
                        <article key={agent.agentId} className={`${styles.agentItemClass} ${agent.agentId === linkedAgentId ? styles.agentItemLinkedClass : ""}`}>
                          <strong className={styles.agentNameClass}>{agent.displayName || agent.agentCode || agent.agentId}</strong>
                          <code className={styles.agentCodeClass}>{agent.agentCode || agent.agentId}</code>
                          <span className={styles.agentMetaClass}>{agent.primaryMode} / {agent.roleKey || "-"}</span>
                        </article>
                      ))
                    ) : (
                      <p className={styles.helperTextClass}>{copy.noAgents}</p>
                    )}
                  </div>
                </section>
              </div>

              <div className={styles.actionsClass}>
                {notice ? <p className={styles.noticeClass}>{notice}</p> : null}
                {saveMutation.error ? <p className={styles.errorTextClass}>{errorMessage(saveMutation.error)}</p> : null}
                {resetMutation.error ? <p className={styles.errorTextClass}>{errorMessage(resetMutation.error)}</p> : null}
                <VButton
                  type="button"
                  className={styles.secondaryButtonClass}
                  icon={<RotateCcw size={15} />}
                  isDisabled={busy || !hasDefault}
                  onPress={() => resetMutation.mutate(editor.templateId)}
                >
                  {copy.reset}
                </VButton>
                <VButton
                  type="button"
                  className={styles.primaryButtonClass}
                  icon={<Save size={15} />}
                  isDisabled={busy}
                  onPress={() => saveMutation.mutate(editor)}
                >
                  {busy ? copy.saving : copy.save}
                </VButton>
              </div>
            </>
          ) : (
            <p className={styles.emptyStateClass}>{templatesQuery.isPending ? copy.loading : copy.emptyEditor}</p>
          )}
        </section>
      </main>
    </section>
  );
}
