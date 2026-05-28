import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { FileText, RefreshCw, RotateCcw, Save, Search, SquarePen } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { AgentInstance, PromptTemplate, PromptTemplateWorkspace } from "../api/types";
import { useAppI18n } from "../i18n/useAppI18n";
import { AgentManagementNav } from "./AgentManagementNav";
import styles from "./PromptTemplatesRoute.module.css";

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

export function PromptTemplatesRoute() {
  const { lang } = useAppI18n();
  const copy = useMemo(() => copyFor(lang), [lang]);
  const queryClient = useQueryClient();
  const [searchParams, setSearchParams] = useSearchParams();
  const initialCategory = (searchParams.get("category") || "all") as PromptCategoryFilter;
  const [categoryFilter, setCategoryFilter] = useState<PromptCategoryFilter>(
    CATEGORY_FILTERS.includes(initialCategory) ? initialCategory : "all",
  );
  const [searchText, setSearchText] = useState("");
  const [activeTemplateId, setActiveTemplateId] = useState("");
  const [editor, setEditor] = useState<PromptEditorState | null>(null);
  const [notice, setNotice] = useState("");

  const templatesQuery = useQuery({
    queryKey: queryKeys.promptTemplates(),
    queryFn: () => fetchJson<PromptTemplateWorkspace>("/api/prompt-templates"),
  });
  const agentsQuery = useQuery({
    queryKey: queryKeys.agents(),
    queryFn: () => fetchJson<AgentInstance[]>("/api/agents"),
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

  useEffect(() => {
    const nextCategory = (searchParams.get("category") || "all") as PromptCategoryFilter;
    const normalizedCategory = CATEGORY_FILTERS.includes(nextCategory) ? nextCategory : "all";
    setCategoryFilter((current) => (current === normalizedCategory ? current : normalizedCategory));
  }, [searchParams]);

  useEffect(() => {
    setSearchParams(categoryFilter === "all" ? {} : { category: categoryFilter }, { replace: true });
  }, [categoryFilter, setSearchParams]);

  useEffect(() => {
    if (activeTemplateId && filteredTemplates.some((template) => template.promptTemplateId === activeTemplateId)) {
      return;
    }
    setActiveTemplateId(filteredTemplates[0]?.promptTemplateId ?? "");
  }, [activeTemplateId, filteredTemplates]);

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
      setEditor(editorFromTemplate(template));
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
      setEditor(editorFromTemplate(template));
      setNotice(copy.resetDone);
      await queryClient.invalidateQueries({ queryKey: queryKeys.promptTemplates() });
      await queryClient.invalidateQueries({ queryKey: ["prompt-templates", template.promptTemplateId, "detail"] });
    },
  });
  const busy = saveMutation.isPending || resetMutation.isPending || detailQuery.isFetching;
  const editableTemplate = detailQuery.data ?? activeTemplate;
  const hasDefault = Boolean(editableTemplate?.defaultContent?.trim());
  const categoriesInUse = new Set(templates.map((template) => template.category || "general"));
  const visibleFilters = CATEGORY_FILTERS.filter((filter) => filter === "all" || filter === "general" || categoriesInUse.has(filter));

  function selectCategory(filter: PromptCategoryFilter) {
    setCategoryFilter(filter);
    setNotice("");
  }

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1>{copy.title}</h1>
          <p>{copy.subtitle}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={() => templatesQuery.refetch()} disabled={templatesQuery.isFetching}>
          <RefreshCw size={15} />
          <span>{copy.refresh}</span>
        </button>
      </header>

      <AgentManagementNav active="prompts" />

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.templates}</span>
          <strong>{templates.length}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.linkedAgents}</span>
          <strong>{agents.filter((agent) => agent.promptTemplateId).length}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.category}</span>
          <strong>{visibleFilters.length - 1}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.source}</span>
          <strong>{templatesQuery.data?.storagePath ?? templatesQuery.data?.path ?? "-"}</strong>
        </section>
      </div>

      <main className={styles.workspace}>
        <aside className={styles.listPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.templates}</p>
              <h2>{filteredTemplates.length} / {templates.length}</h2>
            </div>
            <FileText size={17} />
          </div>

          <label className={styles.searchBox}>
            <Search size={14} />
            <input value={searchText} onChange={(event) => setSearchText(event.target.value)} placeholder={copy.search} />
          </label>

          <div className={styles.filterRow}>
            {visibleFilters.map((filter) => (
              <button
                key={filter}
                type="button"
                className={categoryFilter === filter ? styles.filterButtonActive : styles.filterButton}
                onClick={() => selectCategory(filter)}
              >
                {filter === "all" ? copy.all : categoryLabel(filter, lang)}
              </button>
            ))}
          </div>

          <div className={styles.templateList}>
            {templatesQuery.isError ? (
              <p className={styles.emptyState}>{copy.loadFailed}</p>
            ) : templatesQuery.isPending ? (
              <p className={styles.emptyState}>{copy.loading}</p>
            ) : filteredTemplates.length === 0 ? (
              <p className={styles.emptyState}>{copy.emptyList}</p>
            ) : (
              filteredTemplates.map((template) => {
                const linkedCount = agentsByTemplate.get(template.promptTemplateId)?.length ?? 0;
                return (
                  <button
                    key={template.promptTemplateId}
                    type="button"
                    className={activeTemplateId === template.promptTemplateId ? styles.templateButtonActive : styles.templateButton}
                    onClick={() => {
                      setActiveTemplateId(template.promptTemplateId);
                      setNotice("");
                    }}
                  >
                    <span className={styles.templateMain}>
                      <strong>{template.name || template.promptTemplateId}</strong>
                      <span>{template.promptTemplateId}</span>
                    </span>
                    <span className={styles.templateMeta}>
                      <span className={styles.categoryPill}>{categoryLabel(template.category, lang)}</span>
                      <span>{copy.usage}: {linkedCount}</span>
                      <span>{template.sourcePath || "-"}</span>
                    </span>
                  </button>
                );
              })
            )}
          </div>
        </aside>

        <section className={styles.editorPanel}>
          {editor && editableTemplate ? (
            <>
              <div className={styles.editorHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.editor}</p>
                  <h2>{editableTemplate.promptTemplateId}</h2>
                  <p>{editableTemplate.sourcePath || editableTemplate.category}</p>
                </div>
                <SquarePen size={18} />
              </div>

              <div className={styles.editorMeta}>
                <section className={styles.detailRow}>
                  <span>{copy.category}</span>
                  <strong>{categoryLabel(editor.category, lang)}</strong>
                </section>
                <section className={styles.detailRow}>
                  <span>{copy.sourceExists}</span>
                  <strong>{editableTemplate.sourceExists ? copy.yes : copy.no}</strong>
                </section>
                <section className={styles.detailRow}>
                  <span>{copy.status}</span>
                  <strong>{editableTemplate.status || "active"}</strong>
                </section>
              </div>

              <label className={styles.field}>
                <span>{copy.templates}</span>
                <input value={editor.name} onChange={(event) => setEditor({ ...editor, name: event.target.value })} />
              </label>

              <label className={styles.field}>
                <span>{copy.content}</span>
                <textarea value={editor.content} onChange={(event) => setEditor({ ...editor, content: event.target.value })} />
              </label>

              <div className={styles.bottomGrid}>
                <section className={styles.detailCard}>
                  <div className={styles.contentHeader}>
                    <h3>{copy.defaultPreview}</h3>
                    <span className={hasDefault ? styles.statePill : styles.templateMeta}>{hasDefault ? copy.yes : copy.no}</span>
                  </div>
                  <p className={styles.helperText}>{clip(editableTemplate.defaultContent || copy.resetUnavailable)}</p>
                  <section className={styles.detailRow}>
                    <span>{copy.hash}</span>
                    <strong>{editableTemplate.contentHash || "-"}</strong>
                  </section>
                </section>

                <section className={styles.agentList}>
                  <h3>{copy.linkedAgents}</h3>
                  <div className={styles.agentRows}>
                    {activeAgents.length ? (
                      activeAgents.map((agent) => (
                        <article key={agent.agentId} className={styles.agentItem}>
                          <strong>{agent.displayName || agent.agentCode || agent.agentId}</strong>
                          <code>{agent.agentCode || agent.agentId}</code>
                          <span>{agent.primaryMode} / {agent.roleKey || "-"}</span>
                        </article>
                      ))
                    ) : (
                      <p className={styles.helperText}>{copy.noAgents}</p>
                    )}
                  </div>
                </section>
              </div>

              <div className={styles.actions}>
                {notice ? <p className={styles.notice}>{notice}</p> : null}
                {saveMutation.error ? <p className={styles.errorText}>{errorMessage(saveMutation.error)}</p> : null}
                {resetMutation.error ? <p className={styles.errorText}>{errorMessage(resetMutation.error)}</p> : null}
                <button type="button" className={styles.secondaryButton} disabled={busy || !hasDefault} onClick={() => resetMutation.mutate(editor.templateId)}>
                  <RotateCcw size={15} />
                  <span>{copy.reset}</span>
                </button>
                <button type="button" className={styles.primaryButton} disabled={busy} onClick={() => saveMutation.mutate(editor)}>
                  <Save size={15} />
                  <span>{busy ? copy.saving : copy.save}</span>
                </button>
              </div>
            </>
          ) : (
            <p className={styles.emptyState}>{templatesQuery.isPending ? copy.loading : copy.emptyEditor}</p>
          )}
        </section>
      </main>
    </section>
  );
}
