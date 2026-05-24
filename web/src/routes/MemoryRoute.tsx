import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Brain,
  CheckCircle2,
  Copy as CopyIcon,
  Database,
  Eye,
  FileText,
  Link2,
  Pencil,
  RefreshCw,
  Search,
  Trash2,
  TriangleAlert,
  Undo2,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";

import { fetchJson } from "../api/client";
import { queryKeys } from "../api/queryKeys";
import { MemoryItem, MemoryMutationResponse, MemoryOverview, MemorySection } from "../api/types";
import { resolvePollingInterval, usePageVisibility } from "../app/pollingPolicy";
import { useAppI18n } from "../i18n/useAppI18n";
import styles from "./MemoryRoute.module.css";

type Copy = {
  eyebrow: string;
  title: string;
  subtitle: string;
  refresh: string;
  loading: string;
  loadFailed: string;
  refreshFailed: string;
  sections: string;
  items: string;
  agentVisible: string;
  runtimeInjected: string;
  sourcePath: string;
  sourceApi: string;
  visibility: string;
  agentVisibility: string;
  usedBy: string;
  summary: string;
  rawContent: string;
  noContent: string;
  sourceOrigin: string;
  searchPlaceholder: string;
  allSections: string;
  noMatches: string;
  yes: string;
  no: string;
  inPrompt: string;
  notInPrompt: string;
  canUse: string;
  manualOnly: string;
  missing: string;
  truncated: string;
  warnings: string;
  generatedAt: string;
  sectionCount: string;
  itemCount: string;
  perceptionMatrix: string;
  whereMemoryWorks: string;
  matrixItems: string;
  matrixPrompt: string;
  conversationMemory: string;
  conversationMemoryHint: string;
  selfEvolutionMemory: string;
  selfEvolutionMemoryHint: string;
  supervisedEvolutionMemory: string;
  supervisedEvolutionMemoryHint: string;
  explicitReadMemory: string;
  explicitReadMemoryHint: string;
  filters: string;
  filterAll: string;
  filterPrompt: string;
  filterVisible: string;
  filterManual: string;
  filterMissing: string;
  impact: string;
  impactPromptTitle: string;
  impactPromptBody: string;
  impactVisibleTitle: string;
  impactVisibleBody: string;
  impactManualTitle: string;
  impactManualBody: string;
  copySourceSummary: string;
  copySourcePath: string;
  copyRawContentAction: string;
  copyCurrentLink: string;
  copyDone: string;
  copyFailed: string;
  management: string;
  addMemory: string;
  editMemory: string;
  saveMemory: string;
  cancelEdit: string;
  disableMemory: string;
  restoreMemory: string;
  deleteMemory: string;
  titleField: string;
  summaryField: string;
  contentField: string;
  titlePlaceholder: string;
  summaryPlaceholder: string;
  contentPlaceholder: string;
  managementHint: string;
  overridden: string;
  disabledByUser: string;
  userManaged: string;
  mutationDone: string;
  mutationFailed: string;
};

type FilterMode = "all" | "prompt" | "visible" | "manual" | "missing";
type MemoryChannel = "conversation" | "self_evolution" | "supervised_evolution" | "explicit_read";
type ChannelFilter = MemoryChannel | "";
type MemoryPair = {
  section: MemorySection;
  item: MemoryItem;
};
type EditDraft = {
  mode: "create" | "edit";
  sectionId: string;
  itemId: string;
  title: string;
  summary: string;
  content: string;
};

const FILTER_MODES: FilterMode[] = ["all", "prompt", "visible", "manual", "missing"];
const MEMORY_CHANNELS: MemoryChannel[] = ["conversation", "self_evolution", "supervised_evolution", "explicit_read"];

const COPY: Record<"zh" | "en", Copy> = {
  zh: {
    eyebrow: "Agent Memory",
    title: "记忆",
    subtitle: "按来源聚合 agent 记忆、运行证据和可感知入口，明确哪些内容会进入 prompt。",
    refresh: "刷新",
    loading: "正在整理记忆...",
    loadFailed: "记忆概览加载失败",
    refreshFailed: "记忆概览刷新失败",
    sections: "来源分区",
    items: "记忆条目",
    agentVisible: "agent 可感知",
    runtimeInjected: "运行时注入",
    sourcePath: "路径",
    sourceApi: "接口",
    visibility: "可见性",
    agentVisibility: "Agent 口径",
    usedBy: "作用位置",
    summary: "摘要",
    rawContent: "原文",
    noContent: "没有可展示的原文。",
    sourceOrigin: "来源",
    searchPlaceholder: "搜索来源、路径、摘要或作用位置",
    allSections: "全部来源",
    noMatches: "没有匹配当前搜索的记忆。",
    yes: "是",
    no: "否",
    inPrompt: "进 prompt",
    notInPrompt: "不默认注入",
    canUse: "可使用",
    manualOnly: "显式读取",
    missing: "缺失",
    truncated: "已截断",
    warnings: "诊断提醒",
    generatedAt: "生成时间",
    sectionCount: "分区",
    itemCount: "条目",
    perceptionMatrix: "感知矩阵",
    whereMemoryWorks: "记忆在哪里起作用",
    matrixItems: "条目",
    matrixPrompt: "进 prompt",
    conversationMemory: "对话",
    conversationMemoryHint: "当前会话历史、PromptManager 与 Git 现场。",
    selfEvolutionMemory: "自进化",
    selfEvolutionMemoryHint: "自进化 run prompt、事务和建议基线。",
    supervisedEvolutionMemory: "监督进化",
    supervisedEvolutionMemoryHint: "评测 bundle、监督工作台和策略记录。",
    explicitReadMemory: "显式读取",
    explicitReadMemoryHint: "工具、页面或日志读取后才进入 agent 视野。",
    filters: "快速筛选",
    filterAll: "全部",
    filterPrompt: "进入 prompt",
    filterVisible: "agent 可感知",
    filterManual: "显式读取",
    filterMissing: "缺失/截断",
    impact: "影响说明",
    impactPromptTitle: "会进入运行上下文",
    impactPromptBody: "这条记忆会通过对应 prompt、会话历史或 harness 输入被 agent 直接感知。",
    impactVisibleTitle: "可被 agent 显式读取",
    impactVisibleBody: "这条记忆不会默认进入 prompt；agent 需要通过工具、页面或日志读取后才会使用。",
    impactManualTitle: "只作为展示或诊断证据",
    impactManualBody: "这条内容不应被理解为默认运行记忆；它主要帮助用户审查来源和证据。",
    copySourceSummary: "复制来源摘要",
    copySourcePath: "复制路径",
    copyRawContentAction: "复制原文",
    copyCurrentLink: "复制当前链接",
    copyDone: "已复制",
    copyFailed: "复制失败",
    management: "手动管理",
    addMemory: "新增记忆",
    editMemory: "编辑",
    saveMemory: "保存",
    cancelEdit: "取消",
    disableMemory: "禁用",
    restoreMemory: "恢复",
    deleteMemory: "删除",
    titleField: "标题",
    summaryField: "摘要",
    contentField: "内容",
    titlePlaceholder: "给这条记忆一个便于检查的标题",
    summaryPlaceholder: "一句话说明这条记忆的来源或作用",
    contentPlaceholder: "写入用户要保留、覆盖或标注的记忆内容",
    managementHint: "系统来源只保存覆盖状态，不改原文件；用户手动记忆会写入 workspace/memory/user_memory_overrides.json。",
    overridden: "已覆盖",
    disabledByUser: "已禁用",
    userManaged: "用户记忆",
    mutationDone: "操作已保存",
    mutationFailed: "操作失败",
  },
  en: {
    eyebrow: "Agent Memory",
    title: "Memory",
    subtitle: "Groups agent memory, runtime evidence, and visibility by source, including prompt injection status.",
    refresh: "Refresh",
    loading: "Loading memory...",
    loadFailed: "Memory overview failed to load",
    refreshFailed: "Memory overview refresh failed",
    sections: "Sources",
    items: "Memory Items",
    agentVisible: "agent visible",
    runtimeInjected: "runtime injected",
    sourcePath: "Path",
    sourceApi: "API",
    visibility: "Visibility",
    agentVisibility: "Agent visibility",
    usedBy: "Used by",
    summary: "Summary",
    rawContent: "Raw content",
    noContent: "No raw content to show.",
    sourceOrigin: "Source",
    searchPlaceholder: "Search source, path, summary, or usage",
    allSections: "All sources",
    noMatches: "No memory matched the current search.",
    yes: "Yes",
    no: "No",
    inPrompt: "In prompt",
    notInPrompt: "Not injected",
    canUse: "Usable",
    manualOnly: "Explicit read",
    missing: "Missing",
    truncated: "Truncated",
    warnings: "Warnings",
    generatedAt: "Generated",
    sectionCount: "Sections",
    itemCount: "Items",
    perceptionMatrix: "Perception matrix",
    whereMemoryWorks: "Where memory takes effect",
    matrixItems: "items",
    matrixPrompt: "in prompt",
    conversationMemory: "Conversation",
    conversationMemoryHint: "Current session history, PromptManager, and Git state.",
    selfEvolutionMemory: "Self evolution",
    selfEvolutionMemoryHint: "Run prompt, transactions, and advisory baselines.",
    supervisedEvolutionMemory: "Supervised evolution",
    supervisedEvolutionMemoryHint: "Evaluation bundles, workbench state, and policy records.",
    explicitReadMemory: "Explicit read",
    explicitReadMemoryHint: "Visible only after a tool, page, or log read.",
    filters: "Quick filters",
    filterAll: "All",
    filterPrompt: "In prompt",
    filterVisible: "Agent visible",
    filterManual: "Explicit read",
    filterMissing: "Missing/truncated",
    impact: "Impact",
    impactPromptTitle: "Injected into runtime context",
    impactPromptBody: "This memory can be directly perceived through a prompt section, conversation history, or harness input.",
    impactVisibleTitle: "Explicitly readable by the agent",
    impactVisibleBody: "This memory is not injected by default; the agent must read it through a tool, page, or log workflow.",
    impactManualTitle: "Display or diagnostic evidence",
    impactManualBody: "This content should not be treated as default runtime memory; it mainly helps review source and evidence.",
    copySourceSummary: "Copy source summary",
    copySourcePath: "Copy path",
    copyRawContentAction: "Copy raw content",
    copyCurrentLink: "Copy current link",
    copyDone: "Copied",
    copyFailed: "Copy failed",
    management: "Manual management",
    addMemory: "Add memory",
    editMemory: "Edit",
    saveMemory: "Save",
    cancelEdit: "Cancel",
    disableMemory: "Disable",
    restoreMemory: "Restore",
    deleteMemory: "Delete",
    titleField: "Title",
    summaryField: "Summary",
    contentField: "Content",
    titlePlaceholder: "Name this memory for review",
    summaryPlaceholder: "Briefly describe where it comes from or why it matters",
    contentPlaceholder: "Write the memory content, annotation, or override",
    managementHint: "System sources keep a reversible override and the original file is not changed. User memory is stored in workspace/memory/user_memory_overrides.json.",
    overridden: "Overridden",
    disabledByUser: "Disabled",
    userManaged: "User memory",
    mutationDone: "Saved",
    mutationFailed: "Action failed",
  },
};

function formatTimestamp(value: string, lang: "zh" | "en") {
  const text = String(value || "").trim();
  if (!text) {
    return "-";
  }
  const parsed = new Date(text);
  if (Number.isNaN(parsed.getTime())) {
    return text;
  }
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(parsed);
}

function normalizeText(value: string) {
  return String(value || "").trim().toLowerCase();
}

function searchTarget(section: MemorySection, item: MemoryItem) {
  return normalizeText(
    [
      section.title,
      section.sourceKind,
      section.sourcePath,
      section.sourceApi,
      section.agentVisibility,
      item.title,
      item.kind,
      item.source,
      item.path,
      item.visibilityClass,
      item.channels.join(" "),
      item.summary,
      item.usedBy.join(" "),
    ].join(" "),
  );
}

function sourceOriginLabel(section: MemorySection, item: MemoryItem) {
  const origin = [section.title, item.source].map((value) => String(value || "").trim()).filter(Boolean);
  return Array.from(new Set(origin)).join(" · ") || section.sourceKind;
}

async function copyText(text: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }

  const textArea = document.createElement("textarea");
  textArea.value = text;
  textArea.setAttribute("readonly", "true");
  textArea.style.position = "absolute";
  textArea.style.opacity = "0";
  textArea.style.pointerEvents = "none";
  document.body.appendChild(textArea);
  textArea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textArea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

function normalizeFilterMode(value: string | null): FilterMode {
  return FILTER_MODES.includes(value as FilterMode) ? (value as FilterMode) : "all";
}

function normalizeChannelFilter(value: string | null): ChannelFilter {
  return MEMORY_CHANNELS.includes(value as MemoryChannel) ? (value as MemoryChannel) : "";
}

function itemMatchesFilter(item: MemoryItem, filterMode: FilterMode) {
  if (filterMode === "prompt") {
    return item.visibilityClass === "prompt";
  }
  if (filterMode === "visible") {
    return item.agentVisible;
  }
  if (filterMode === "manual") {
    return item.visibilityClass === "agent_visible" || item.visibilityClass === "manual" || item.channels.includes("explicit_read");
  }
  if (filterMode === "missing") {
    return item.visibilityClass === "missing" || !item.exists || item.contentTruncated;
  }
  return true;
}

function itemMatchesChannelFilter(item: MemoryItem, channelFilter: ChannelFilter) {
  return !channelFilter || item.channels.includes(channelFilter);
}

function filterSections(
  sections: MemorySection[],
  activeSectionId: string,
  searchText: string,
  filterMode: FilterMode,
  channelFilter: ChannelFilter,
) {
  const query = normalizeText(searchText);
  return sections
    .filter((section) => !activeSectionId || section.id === activeSectionId)
    .map((section) => ({
      ...section,
      items: section.items.filter(
        (item) =>
          itemMatchesFilter(item, filterMode)
          && itemMatchesChannelFilter(item, channelFilter)
          && (!query || searchTarget(section, item).includes(query)),
      ),
    }))
    .filter((section) => section.items.length > 0 || !query);
}

function flattenSections(sections: MemorySection[]): MemoryPair[] {
  return sections.flatMap((section) =>
    section.items.map((item) => ({
      section,
      item,
    })),
  );
}

function matchesMemoryChannel(channelId: MemoryChannel, pair: MemoryPair) {
  return pair.item.channels.includes(channelId);
}

function countChannelItems(pairs: MemoryPair[], channelId: MemoryChannel) {
  const items = pairs.filter((pair) => matchesMemoryChannel(channelId, pair));
  return {
    itemCount: items.length,
    promptCount: items.filter(({ item }) => item.inPrompt).length,
  };
}

function channelLabel(copy: Copy, channelId: MemoryChannel) {
  if (channelId === "conversation") {
    return copy.conversationMemory;
  }
  if (channelId === "self_evolution") {
    return copy.selfEvolutionMemory;
  }
  if (channelId === "supervised_evolution") {
    return copy.supervisedEvolutionMemory;
  }
  return copy.explicitReadMemory;
}

function channelHint(copy: Copy, channelId: MemoryChannel) {
  if (channelId === "conversation") {
    return copy.conversationMemoryHint;
  }
  if (channelId === "self_evolution") {
    return copy.selfEvolutionMemoryHint;
  }
  if (channelId === "supervised_evolution") {
    return copy.supervisedEvolutionMemoryHint;
  }
  return copy.explicitReadMemoryHint;
}

function itemChannelPills(copy: Copy, item: MemoryItem) {
  const channels = item.channels as MemoryChannel[];
  if (!channels.length) {
    return item.visibilityClass === "diagnostic"
      ? [{ label: copy.impactManualTitle, hint: copy.impactManualBody }]
      : [];
  }
  return channels.map((channelId) => ({
    label: channelLabel(copy, channelId),
    hint: channelHint(copy, channelId),
  }));
}

function channelFilterLabel(copy: Copy, channelFilter: ChannelFilter) {
  if (channelFilter === "conversation") {
    return copy.conversationMemory;
  }
  if (channelFilter === "self_evolution") {
    return copy.selfEvolutionMemory;
  }
  if (channelFilter === "supervised_evolution") {
    return copy.supervisedEvolutionMemory;
  }
  if (channelFilter === "explicit_read") {
    return copy.explicitReadMemory;
  }
  return "";
}

function filterCount(pairs: MemoryPair[], filterMode: FilterMode) {
  return pairs.filter(({ item }) => itemMatchesFilter(item, filterMode)).length;
}

function statusClassName(active: boolean, injected: boolean) {
  if (injected) {
    return `${styles.statusPill} ${styles.statusPillPrompt}`;
  }
  if (active) {
    return `${styles.statusPill} ${styles.statusPillVisible}`;
  }
  return `${styles.statusPill} ${styles.statusPillMuted}`;
}

function contentLanguage(contentType: string) {
  if (contentType === "json") {
    return "json";
  }
  if (contentType === "markdown") {
    return "markdown";
  }
  if (contentType === "html") {
    return "html";
  }
  return "text";
}

function impactCopy(copy: Copy, item: MemoryItem) {
  if (item.managedState?.disabled) {
    return {
      title: copy.disabledByUser,
      body: item.managedState.actionHint || copy.managementHint,
    };
  }
  if (item.inPrompt) {
    return {
      title: copy.impactPromptTitle,
      body: copy.impactPromptBody,
    };
  }
  if (item.agentVisible) {
    return {
      title: copy.impactVisibleTitle,
      body: copy.impactVisibleBody,
    };
  }
  return {
    title: copy.impactManualTitle,
    body: copy.impactManualBody,
  };
}

function buildInspectionText(copy: Copy, section: MemorySection, item: MemoryItem, url: string) {
  return [
    `${section.title} / ${item.title}`,
    `${copy.sourceOrigin}: ${sourceOriginLabel(section, item)}`,
    `${copy.sourcePath}: ${item.path || "-"}`,
    `${copy.sourceApi}: ${section.sourceApi || "-"}`,
    `${copy.visibility}: ${item.visibilityClass} · ${copy.agentVisibility}: ${section.agentVisibility}`,
    `${copy.usedBy}: ${item.usedBy.join(" · ") || "-"}`,
    url ? `URL: ${url}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function buildMemorySearchParams(
  activeSectionId: string,
  activeItemId: string,
  activeFilter: FilterMode,
  activeChannel: ChannelFilter,
  searchText: string,
) {
  const next = new URLSearchParams();
  if (activeSectionId) {
    next.set("section", activeSectionId);
  }
  if (activeItemId) {
    next.set("item", activeItemId);
  }
  if (activeFilter !== "all") {
    next.set("filter", activeFilter);
  }
  if (activeChannel) {
    next.set("channel", activeChannel);
  }
  if (searchText.trim()) {
    next.set("q", searchText.trim());
  }
  return next;
}

function buildMemoryLink(
  activeSectionId: string,
  activeItemId: string,
  activeFilter: FilterMode,
  activeChannel: ChannelFilter,
  searchText: string,
) {
  if (typeof window === "undefined") {
    return "";
  }
  const next = buildMemorySearchParams(activeSectionId, activeItemId, activeFilter, activeChannel, searchText);
  const query = next.toString();
  return `${window.location.origin}${window.location.pathname}${query ? `?${query}` : ""}${window.location.hash}`;
}

function newCreateDraft(): EditDraft {
  return {
    mode: "create",
    sectionId: "user-managed-memory",
    itemId: "",
    title: "",
    summary: "",
    content: "",
  };
}

function draftFromItem(section: MemorySection, item: MemoryItem): EditDraft {
  return {
    mode: "edit",
    sectionId: section.id,
    itemId: item.id,
    title: item.title,
    summary: item.summary,
    content: item.content,
  };
}

function memoryMutationEndpoint(sectionId: string, itemId: string, suffix = "") {
  return `/api/memory/items/${encodeURIComponent(sectionId)}/${encodeURIComponent(itemId)}${suffix}`;
}

export function MemoryRoute() {
  const { lang } = useAppI18n();
  const copy = COPY[lang];
  const queryClient = useQueryClient();
  const pageVisible = usePageVisibility();
  const [searchParams, setSearchParams] = useSearchParams();
  const searchParamText = searchParams.toString();
  const [activeSectionId, setActiveSectionId] = useState(() => searchParams.get("section") ?? "");
  const [activeItemId, setActiveItemId] = useState(() => searchParams.get("item") ?? "");
  const [activeFilter, setActiveFilter] = useState<FilterMode>(() => normalizeFilterMode(searchParams.get("filter")));
  const [activeChannel, setActiveChannel] = useState<ChannelFilter>(() => normalizeChannelFilter(searchParams.get("channel")));
  const [searchText, setSearchText] = useState(() => searchParams.get("q") ?? "");
  const [copyFeedback, setCopyFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });
  const [editDraft, setEditDraft] = useState<EditDraft | null>(null);
  const [mutationFeedback, setMutationFeedback] = useState<{ tone: "idle" | "success" | "error"; text: string }>({
    tone: "idle",
    text: "",
  });

  const overviewQuery = useQuery({
    queryKey: queryKeys.memoryOverview(),
    queryFn: () => fetchJson<MemoryOverview>("/api/memory/overview"),
    refetchInterval: resolvePollingInterval(pageVisible, 30_000),
    refetchIntervalInBackground: false,
  });

  const memoryMutation = useMutation({
    mutationFn: async (draft: EditDraft) => {
      const body = JSON.stringify({
        title: draft.title,
        summary: draft.summary,
        content: draft.content,
      });
      if (draft.mode === "create") {
        return fetchJson<MemoryMutationResponse>("/api/memory/items", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body,
        });
      }
      return fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(draft.sectionId, draft.itemId), {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body,
      });
    },
    onSuccess: (payload) => {
      setEditDraft(null);
      setActiveSectionId(payload.sectionId);
      setActiveItemId(payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const deleteMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(sectionId, itemId), {
        method: "DELETE",
      }),
    onSuccess: (payload) => {
      setActiveSectionId(payload.sectionId === "user-managed-memory" ? "" : payload.sectionId);
      setActiveItemId(payload.sectionId === "user-managed-memory" ? "" : payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const restoreMemoryMutation = useMutation({
    mutationFn: async ({ sectionId, itemId }: { sectionId: string; itemId: string }) =>
      fetchJson<MemoryMutationResponse>(memoryMutationEndpoint(sectionId, itemId, "/restore"), {
        method: "POST",
      }),
    onSuccess: (payload) => {
      setActiveSectionId(payload.sectionId);
      setActiveItemId(payload.itemId);
      setMutationFeedback({ tone: "success", text: copy.mutationDone });
      void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
    },
    onError: (error) => {
      setMutationFeedback({
        tone: "error",
        text: `${copy.mutationFailed}: ${error instanceof Error ? error.message : String(error)}`,
      });
    },
  });

  const overview = overviewQuery.data;
  const sections = overview?.sections ?? [];
  const allPairs = useMemo(() => flattenSections(sections), [sections]);
  const matrixCards = useMemo(
    () => [
      {
        id: "conversation",
        channel: "conversation" as const,
        title: copy.conversationMemory,
        hint: copy.conversationMemoryHint,
        ...countChannelItems(allPairs, "conversation"),
      },
      {
        id: "self",
        channel: "self_evolution" as const,
        title: copy.selfEvolutionMemory,
        hint: copy.selfEvolutionMemoryHint,
        ...countChannelItems(allPairs, "self_evolution"),
      },
      {
        id: "supervised",
        channel: "supervised_evolution" as const,
        title: copy.supervisedEvolutionMemory,
        hint: copy.supervisedEvolutionMemoryHint,
        ...countChannelItems(allPairs, "supervised_evolution"),
      },
      {
        id: "explicit",
        channel: "explicit_read" as const,
        title: copy.explicitReadMemory,
        hint: copy.explicitReadMemoryHint,
        ...countChannelItems(allPairs, "explicit_read"),
      },
    ],
    [allPairs, copy],
  );
  const visibleSectionsBySource = useMemo(
    () => filterSections(sections, "", searchText, activeFilter, activeChannel),
    [activeChannel, activeFilter, searchText, sections],
  );
  const sourceSectionMetrics = useMemo(
    () =>
      new Map(
        visibleSectionsBySource.map((section) => [
          section.id,
          {
            itemCount: section.items.length,
            promptCount: section.items.filter((item) => item.inPrompt).length,
          },
        ]),
      ),
    [visibleSectionsBySource],
  );
  const filterOptions = useMemo(
    () => [
      { id: "all" as const, label: copy.filterAll, count: filterCount(allPairs, "all") },
      { id: "prompt" as const, label: copy.filterPrompt, count: filterCount(allPairs, "prompt") },
      { id: "visible" as const, label: copy.filterVisible, count: filterCount(allPairs, "visible") },
      { id: "manual" as const, label: copy.filterManual, count: filterCount(allPairs, "manual") },
      { id: "missing" as const, label: copy.filterMissing, count: filterCount(allPairs, "missing") },
    ],
    [allPairs, copy],
  );
  const visibleSections = useMemo(
    () => filterSections(sections, activeSectionId, searchText, activeFilter, activeChannel),
    [activeChannel, activeFilter, activeSectionId, searchText, sections],
  );
  const flatVisibleItems = useMemo(
    () =>
      visibleSections.flatMap((section) =>
        section.items.map((item) => ({
          section,
          item,
        })),
      ),
    [visibleSections],
  );
  const activePair =
    flatVisibleItems.find(({ item }) => item.id === activeItemId) ?? flatVisibleItems[0] ?? null;
  const activeItem = activePair?.item ?? null;
  const activeSection = activePair?.section ?? null;
  const activeImpact = activeItem ? impactCopy(copy, activeItem) : null;
  const hasOverviewSections = sections.length > 0;
  const showBlockingOverviewError = overviewQuery.isError && !hasOverviewSections;
  const showRefreshNotice = overviewQuery.isError && hasOverviewSections;
  const selectedSectionVisibleCount = activeSectionId
    ? sourceSectionMetrics.get(activeSectionId)?.itemCount ?? 0
    : flatVisibleItems.length;
  const selectedSectionPromptCount = activeSectionId
    ? sourceSectionMetrics.get(activeSectionId)?.promptCount ?? 0
    : flatVisibleItems.filter(({ item }) => item.inPrompt).length;
  const canCopyRawContent = Boolean(activeItem?.content);

  useEffect(() => {
    const sectionParam = searchParams.get("section") ?? "";
    const itemParam = searchParams.get("item") ?? "";
    const filterParam = normalizeFilterMode(searchParams.get("filter"));
    const channelParam = normalizeChannelFilter(searchParams.get("channel"));
    const queryParam = searchParams.get("q") ?? "";
    if (sectionParam !== activeSectionId) {
      setActiveSectionId(sectionParam);
    }
    if (itemParam !== activeItemId) {
      setActiveItemId(itemParam);
    }
    if (filterParam !== activeFilter) {
      setActiveFilter(filterParam);
    }
    if (channelParam !== activeChannel) {
      setActiveChannel(channelParam);
    }
    if (queryParam !== searchText) {
      setSearchText(queryParam);
    }
  }, [searchParamText]);

  useEffect(() => {
    const next = buildMemorySearchParams(activeSectionId, activeItemId, activeFilter, activeChannel, searchText);
    if (next.toString() !== searchParamText) {
      setSearchParams(next, { replace: true });
    }
  }, [activeChannel, activeFilter, activeItemId, activeSectionId, searchParamText, searchText, setSearchParams]);

  useEffect(() => {
    if (copyFeedback.tone === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => {
      setCopyFeedback({ tone: "idle", text: "" });
    }, 1800);
    return () => window.clearTimeout(timeout);
  }, [copyFeedback]);

  useEffect(() => {
    if (mutationFeedback.tone === "idle") {
      return;
    }
    const timeout = window.setTimeout(() => {
      setMutationFeedback({ tone: "idle", text: "" });
    }, 2200);
    return () => window.clearTimeout(timeout);
  }, [mutationFeedback]);

  useEffect(() => {
    if (!sections.length) {
      return;
    }
    if (activeSectionId && !sections.some((section) => section.id === activeSectionId)) {
      setActiveSectionId("");
    }
  }, [activeSectionId, sections]);

  useEffect(() => {
    if (!activeItemId || flatVisibleItems.some(({ item }) => item.id === activeItemId)) {
      return;
    }
    setActiveItemId(flatVisibleItems[0]?.item.id ?? "");
  }, [activeItemId, flatVisibleItems]);

  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: queryKeys.memoryOverview() });
  };

  const selectedSection = sections.find((section) => section.id === activeSectionId) ?? null;
  const warningCount = overview?.summary.warnings.length ?? 0;
  const handleChannelCardClick = (channel: MemoryChannel) => {
    setActiveSectionId("");
    setActiveItemId("");
    setActiveChannel((current) => (current === channel ? "" : channel));
  };
  const currentUrl = useMemo(
    () => buildMemoryLink(activeSectionId, activeItemId, activeFilter, activeChannel, searchText),
    [activeChannel, activeFilter, activeItemId, activeSectionId, searchText],
  );
  const handleCopySourceSummary = async () => {
    if (!activeSection || !activeItem) {
      return;
    }
    try {
      await copyText(buildInspectionText(copy, activeSection, activeItem, currentUrl));
      setCopyFeedback({ tone: "success", text: `${copy.copySourceSummary} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copySourceSummary} · ${copy.copyFailed}` });
    }
  };
  const handleCopySourcePath = async () => {
    if (!activeSection || !activeItem) {
      return;
    }
    const sourcePath = activeItem.path || activeItem.source || activeSection.sourcePath || "";
    if (!sourcePath) {
      return;
    }
    try {
      await copyText(sourcePath);
      setCopyFeedback({ tone: "success", text: `${copy.copySourcePath} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copySourcePath} · ${copy.copyFailed}` });
    }
  };
  const handleCopyRawContent = async () => {
    if (!activeItem?.content) {
      return;
    }
    try {
      await copyText(activeItem.content);
      setCopyFeedback({ tone: "success", text: `${copy.copyRawContentAction} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copyRawContentAction} · ${copy.copyFailed}` });
    }
  };
  const handleCopyCurrentLink = async () => {
    if (!currentUrl) {
      return;
    }
    try {
      await copyText(currentUrl);
      setCopyFeedback({ tone: "success", text: `${copy.copyCurrentLink} · ${copy.copyDone}` });
    } catch {
      setCopyFeedback({ tone: "error", text: `${copy.copyCurrentLink} · ${copy.copyFailed}` });
    }
  };
  const startCreate = () => {
    setEditDraft(newCreateDraft());
    setActiveSectionId("user-managed-memory");
    setActiveItemId("");
  };
  const startEdit = () => {
    if (!activeSection || !activeItem) {
      return;
    }
    setEditDraft(draftFromItem(activeSection, activeItem));
  };
  const saveDraft = () => {
    if (!editDraft || !editDraft.title.trim()) {
      setMutationFeedback({ tone: "error", text: `${copy.mutationFailed}: ${copy.titleField}` });
      return;
    }
    memoryMutation.mutate(editDraft);
  };
  const cancelDraft = () => {
    setEditDraft(null);
  };
  const disableOrDeleteActiveItem = () => {
    if (!activeSection || !activeItem || !activeItem.managedState?.deletable) {
      return;
    }
    deleteMemoryMutation.mutate({ sectionId: activeSection.id, itemId: activeItem.id });
  };
  const restoreActiveItem = () => {
    if (!activeSection || !activeItem || !activeItem.managedState?.restorable) {
      return;
    }
    restoreMemoryMutation.mutate({ sectionId: activeSection.id, itemId: activeItem.id });
  };
  const mutationBusy = memoryMutation.isPending || deleteMemoryMutation.isPending || restoreMemoryMutation.isPending;

  return (
    <section className={styles.route}>
      <header className={styles.header}>
        <div>
          <p className={styles.eyebrow}>{copy.eyebrow}</p>
          <h1 className={styles.title}>{copy.title}</h1>
          <p className={styles.subtitle}>{copy.subtitle}</p>
        </div>
        <button type="button" className={styles.refreshButton} onClick={refresh}>
          <RefreshCw size={16} />
          {copy.refresh}
        </button>
        <button type="button" className={styles.refreshButton} onClick={startCreate}>
          <Pencil size={16} />
          {copy.addMemory}
        </button>
      </header>

      <div className={styles.summaryGrid}>
        <section className={styles.summaryCard}>
          <span>{copy.sectionCount}</span>
          <strong>{overview?.summary.sectionCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.itemCount}</span>
          <strong>{overview?.summary.itemCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.agentVisible}</span>
          <strong>{overview?.summary.agentVisibleCount ?? 0}</strong>
        </section>
        <section className={styles.summaryCard}>
          <span>{copy.runtimeInjected}</span>
          <strong>{overview?.summary.runtimeInjectedCount ?? 0}</strong>
        </section>
      </div>

      <section className={styles.matrixPanel} aria-label={copy.perceptionMatrix}>
        <div className={styles.matrixHeader}>
          <div>
            <p className={styles.panelEyebrow}>{copy.perceptionMatrix}</p>
            <h2>{copy.whereMemoryWorks}</h2>
          </div>
          <div className={styles.matrixHeaderMeta}>
            {activeChannel ? (
              <span className={styles.activeChannelPill}>{channelFilterLabel(copy, activeChannel)}</span>
            ) : null}
            {overview ? <span className={styles.countPill}>{formatTimestamp(overview.generatedAt, lang)}</span> : null}
          </div>
        </div>
        <div className={styles.matrixGrid}>
          {matrixCards.map((card) => (
            <button
              key={card.id}
              type="button"
              className={
                activeChannel === card.channel
                  ? `${styles.matrixCard} ${styles.matrixCardButton} ${styles.matrixCardActive}`
                  : `${styles.matrixCard} ${styles.matrixCardButton}`
              }
              onClick={() => handleChannelCardClick(card.channel)}
              aria-pressed={activeChannel === card.channel}
            >
              <div>
                <strong>{card.title}</strong>
                <span>{card.hint}</span>
              </div>
              <dl>
                <div>
                  <dt>{copy.matrixItems}</dt>
                  <dd>{card.itemCount}</dd>
                </div>
                <div>
                  <dt>{copy.matrixPrompt}</dt>
                  <dd>{card.promptCount}</dd>
                </div>
              </dl>
            </button>
          ))}
        </div>
      </section>

      {warningCount > 0 ? (
        <section className={styles.warningStrip} aria-label={copy.warnings}>
          <TriangleAlert size={16} />
          <strong>{copy.warnings}</strong>
          <span>{overview?.summary.warnings.join("；")}</span>
        </section>
      ) : null}

      <div className={styles.workspace}>
        <aside className={styles.sourcePanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.sections}</p>
              <h2>{selectedSection?.title ?? copy.allSections}</h2>
            </div>
            <span className={styles.countPill}>{selectedSectionVisibleCount}</span>
          </div>

          <label className={styles.searchBox}>
            <Search size={15} />
            <input
              value={searchText}
              placeholder={copy.searchPlaceholder}
              onChange={(event) => setSearchText(event.target.value)}
            />
          </label>

          <div className={styles.filterGroup} aria-label={copy.filters}>
            {filterOptions.map((option) => (
              <button
                key={option.id}
                type="button"
                className={option.id === activeFilter ? `${styles.filterButton} ${styles.filterButtonActive}` : styles.filterButton}
                onClick={() => setActiveFilter(option.id)}
                aria-pressed={option.id === activeFilter}
              >
                <span>{option.label}</span>
                <strong>{option.count}</strong>
              </button>
            ))}
          </div>

          <button
            type="button"
            className={!activeSectionId ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
            onClick={() => setActiveSectionId("")}
          >
            <span className={styles.sourceIcon}>
              <Database size={15} />
            </span>
            <span className={styles.sourceCopy}>
              <strong>{copy.allSections}</strong>
              <span>
                {copy.items}: {flatVisibleItems.length}
                {selectedSectionPromptCount ? ` / ${selectedSectionPromptCount}` : ""}
              </span>
            </span>
          </button>

          <nav className={styles.sourceList} aria-label={copy.sections}>
            {sections.map((section) => {
              const active = section.id === activeSectionId;
              const metrics = sourceSectionMetrics.get(section.id);
              return (
                <button
                  key={section.id}
                  type="button"
                  className={active ? `${styles.sourceButton} ${styles.sourceButtonActive}` : styles.sourceButton}
                  onClick={() => setActiveSectionId(section.id)}
                  aria-pressed={active}
                >
                  <span className={styles.sourceIcon}>
                    <Brain size={15} />
                  </span>
                  <span className={styles.sourceCopy}>
                    <strong>{section.title}</strong>
                    <span>{[section.sourcePath, section.sourceApi].filter(Boolean).join(" · ") || section.sourceKind}</span>
                  </span>
                  <span className={styles.sourceStats}>
                    {metrics?.itemCount ?? 0}
                    {metrics?.promptCount ? ` / ${metrics.promptCount}` : ""}
                  </span>
                </button>
              );
            })}
          </nav>
        </aside>

        <main className={styles.itemPanel}>
          <div className={styles.panelHeader}>
            <div>
              <p className={styles.panelEyebrow}>{copy.items}</p>
              <h2>{activeSection?.title ?? copy.allSections}</h2>
            </div>
            <span className={styles.countPill}>{flatVisibleItems.length}</span>
          </div>

          {showRefreshNotice ? (
            <section className={styles.panelNotice} aria-label={copy.refreshFailed}>
              <TriangleAlert size={16} />
              <strong>{copy.refreshFailed}</strong>
              <span>{overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}</span>
            </section>
          ) : null}

          {overviewQuery.isPending && !hasOverviewSections ? (
            <div className={styles.emptyState}>{copy.loading}</div>
          ) : showBlockingOverviewError ? (
            <div className={styles.emptyState}>
              {copy.loadFailed}: {overviewQuery.error instanceof Error ? overviewQuery.error.message : String(overviewQuery.error)}
            </div>
          ) : !flatVisibleItems.length ? (
            <div className={styles.emptyState}>{copy.noMatches}</div>
          ) : (
            <div className={styles.itemList}>
              {flatVisibleItems.map(({ section, item }) => {
                const active = item.id === activeItem?.id;
                return (
                  <button
                    key={`${section.id}:${item.id}`}
                    type="button"
                    className={active ? `${styles.itemButton} ${styles.itemButtonActive}` : styles.itemButton}
                    onClick={() => setActiveItemId(item.id)}
                    aria-pressed={active}
                  >
                    <span className={styles.itemHeader}>
                      <strong>{item.title}</strong>
                      <span>{formatTimestamp(item.updatedAt, lang)}</span>
                    </span>
                    <span className={styles.itemOrigin}>
                      {copy.sourceOrigin}: {sourceOriginLabel(section, item)}
                    </span>
                    <span className={styles.itemPath}>{item.path || item.source}</span>
                    <span className={styles.itemSummary}>{item.summary}</span>
                    <span className={styles.itemBadges}>
                      <span className={statusClassName(item.agentVisible, item.inPrompt)}>
                        {item.inPrompt ? copy.inPrompt : item.agentVisible ? copy.canUse : copy.manualOnly}
                      </span>
                      {item.managedState?.userManaged ? <span className={styles.statusPill}>{copy.userManaged}</span> : null}
                      {item.managedState?.overridden ? <span className={styles.statusPill}>{copy.overridden}</span> : null}
                      {item.managedState?.disabled ? <span className={styles.statusPill}>{copy.disabledByUser}</span> : null}
                      {itemChannelPills(copy, item).map((pill) => (
                        <span key={`${item.id}:${pill.label}`} className={styles.channelPill} title={pill.hint}>
                          {pill.label}
                        </span>
                      ))}
                      {!item.exists ? <span className={styles.statusPill}>{copy.missing}</span> : null}
                      {item.contentTruncated ? <span className={styles.statusPill}>{copy.truncated}</span> : null}
                    </span>
                  </button>
                );
              })}
            </div>
          )}
        </main>

        <aside className={styles.detailPanel}>
          {editDraft ? (
            <section className={styles.managementPanel} aria-label={copy.management}>
              <div className={styles.managementHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{copy.management}</p>
                  <h2>{editDraft.mode === "create" ? copy.addMemory : copy.editMemory}</h2>
                </div>
                <button type="button" className={styles.iconButton} onClick={cancelDraft} disabled={mutationBusy}>
                  <XCircle size={16} />
                  <span>{copy.cancelEdit}</span>
                </button>
              </div>
              <p>{copy.managementHint}</p>
              <label className={styles.fieldStack}>
                <span>{copy.titleField}</span>
                <input
                  value={editDraft.title}
                  placeholder={copy.titlePlaceholder}
                  onChange={(event) =>
                    setEditDraft((current) => (current ? { ...current, title: event.target.value } : current))
                  }
                />
              </label>
              <label className={styles.fieldStack}>
                <span>{copy.summaryField}</span>
                <input
                  value={editDraft.summary}
                  placeholder={copy.summaryPlaceholder}
                  onChange={(event) =>
                    setEditDraft((current) => (current ? { ...current, summary: event.target.value } : current))
                  }
                />
              </label>
              <label className={styles.fieldStack}>
                <span>{copy.contentField}</span>
                <textarea
                  value={editDraft.content}
                  placeholder={copy.contentPlaceholder}
                  onChange={(event) =>
                    setEditDraft((current) => (current ? { ...current, content: event.target.value } : current))
                  }
                />
              </label>
              <div className={styles.managementActions}>
                <button type="button" className={styles.primaryActionButton} onClick={saveDraft} disabled={mutationBusy}>
                  <CheckCircle2 size={15} />
                  <span>{copy.saveMemory}</span>
                </button>
                <button type="button" className={styles.detailActionButton} onClick={cancelDraft} disabled={mutationBusy}>
                  <XCircle size={15} />
                  <span>{copy.cancelEdit}</span>
                </button>
              </div>
              {mutationFeedback.tone !== "idle" ? (
                <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
                  {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
                  <span>{mutationFeedback.text}</span>
                </p>
              ) : null}
            </section>
          ) : null}

          {activeItem && activeSection ? (
            <>
              <section className={styles.detailHeader}>
                <div>
                  <p className={styles.panelEyebrow}>{activeSection.title}</p>
                  <h2>{activeItem.title}</h2>
                  <p>{activeItem.summary}</p>
                </div>
                <span className={statusClassName(activeItem.agentVisible, activeItem.inPrompt)}>
                  {activeItem.inPrompt ? copy.inPrompt : activeItem.agentVisible ? copy.canUse : copy.manualOnly}
                </span>
              </section>

              {activeImpact ? (
                <section className={styles.impactPanel}>
                  <div className={styles.visibilityHeader}>
                    <Brain size={16} />
                    <div>
                      <strong>{copy.impact}</strong>
                      <p>{activeImpact.title}</p>
                    </div>
                  </div>
                  <p>{activeImpact.body}</p>
                </section>
              ) : null}

              <div className={styles.detailActions}>
                <button type="button" className={styles.detailActionButton} onClick={handleCopySourceSummary}>
                  <CopyIcon size={14} />
                  <span>{copy.copySourceSummary}</span>
                </button>
                <button type="button" className={styles.detailActionButton} onClick={handleCopySourcePath}>
                  <FileText size={14} />
                  <span>{copy.copySourcePath}</span>
                </button>
                <button
                  type="button"
                  className={styles.detailActionButton}
                  onClick={handleCopyRawContent}
                  disabled={!canCopyRawContent}
                  title={!canCopyRawContent ? copy.noContent : undefined}
                >
                  <FileText size={14} />
                  <span>{copy.copyRawContentAction}</span>
                </button>
                <button type="button" className={styles.detailActionButton} onClick={handleCopyCurrentLink}>
                  <Link2 size={14} />
                  <span>{copy.copyCurrentLink}</span>
                </button>
              </div>

              {copyFeedback.tone !== "idle" ? (
                <p className={styles.copyNotice} data-tone={copyFeedback.tone}>
                  {copyFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
                  <span>{copyFeedback.text}</span>
                </p>
              ) : null}

              <section className={styles.managementPanel} aria-label={copy.management}>
                <div className={styles.managementHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.management}</p>
                    <h2>{activeItem.managedState?.userManaged ? copy.userManaged : activeItem.managedState?.overridden ? copy.overridden : copy.management}</h2>
                  </div>
                  <span className={styles.countPill}>
                    {activeItem.managedState?.disabled
                      ? copy.disabledByUser
                      : activeItem.managedState?.userManaged
                        ? copy.userManaged
                        : activeItem.managedState?.overridden
                          ? copy.overridden
                          : copy.canUse}
                  </span>
                </div>
                <p>{activeItem.managedState?.actionHint || copy.managementHint}</p>
                <div className={styles.managementActions}>
                  <button
                    type="button"
                    className={styles.detailActionButton}
                    onClick={startEdit}
                    disabled={!activeItem.managedState?.editable || mutationBusy}
                  >
                    <Pencil size={15} />
                    <span>{copy.editMemory}</span>
                  </button>
                  {activeItem.managedState?.restorable ? (
                    <button
                      type="button"
                      className={styles.detailActionButton}
                      onClick={restoreActiveItem}
                      disabled={mutationBusy}
                    >
                      <Undo2 size={15} />
                      <span>{copy.restoreMemory}</span>
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className={styles.detailActionButton}
                    onClick={disableOrDeleteActiveItem}
                    disabled={!activeItem.managedState?.deletable || mutationBusy}
                  >
                    <Trash2 size={15} />
                    <span>{activeItem.managedState?.userManaged ? copy.deleteMemory : copy.disableMemory}</span>
                  </button>
                </div>
              </section>

              {mutationFeedback.tone !== "idle" ? (
                <p className={styles.copyNotice} data-tone={mutationFeedback.tone}>
                  {mutationFeedback.tone === "success" ? <CheckCircle2 size={14} /> : <TriangleAlert size={14} />}
                  <span>{mutationFeedback.text}</span>
                </p>
              ) : null}

              <div className={styles.factGrid}>
                <section>
                  <span>{copy.sourcePath}</span>
                  <strong title={activeItem.path}>{activeItem.path || "-"}</strong>
                </section>
                <section>
                  <span>{copy.sourceApi}</span>
                  <strong title={activeSection.sourceApi}>{activeSection.sourceApi || "-"}</strong>
                </section>
                <section>
                  <span>{copy.agentVisible}</span>
                  <strong>{activeItem.agentVisible ? copy.yes : copy.no}</strong>
                </section>
                <section>
                  <span>{copy.runtimeInjected}</span>
                  <strong>{activeItem.inPrompt ? copy.yes : copy.no}</strong>
                </section>
              </div>

              <section className={styles.visibilityPanel}>
                <div className={styles.visibilityHeader}>
                  <Eye size={16} />
                  <div>
                    <strong>{copy.agentVisibility}</strong>
                    <p>{activeSection.agentVisibility}</p>
                  </div>
                </div>
                <div className={styles.usageList}>
                  {itemChannelPills(copy, activeItem).map((pill) => (
                    <span key={`${activeItem.id}:channel:${pill.label}`} title={pill.hint}>
                      <CheckCircle2 size={13} />
                      {pill.label}
                    </span>
                  ))}
                </div>
                <div className={styles.usageList}>
                  {activeItem.usedBy.map((usage) => (
                    <span key={`${activeItem.id}:${usage}`}>
                      <CheckCircle2 size={13} />
                      {usage}
                    </span>
                  ))}
                </div>
              </section>

              <section className={styles.sectionPanel}>
                <div className={styles.panelHeader}>
                  <div>
                    <p className={styles.panelEyebrow}>{copy.summary}</p>
                    <h3>{activeSection.sourceKind}</h3>
                  </div>
                  <span className={styles.countPill}>{formatTimestamp(activeSection.updatedAt, lang)}</span>
                </div>
                <p>{activeSection.summary}</p>
              </section>

              <details className={styles.rawPanel} open>
                <summary>
                  <FileText size={15} />
                  <span>{copy.rawContent}</span>
                  <code>{activeItem.contentType}</code>
                </summary>
                {activeItem.content ? (
                  <pre data-language={contentLanguage(activeItem.contentType)}>{activeItem.content}</pre>
                ) : (
                  <p>{copy.noContent}</p>
                )}
              </details>
            </>
          ) : editDraft ? null : (
            <section className={styles.emptyDetail}>
              <Brain size={24} />
              <strong>{copy.title}</strong>
              <p>{overviewQuery.isPending ? copy.loading : copy.noMatches}</p>
            </section>
          )}

          {overview ? (
            <p className={styles.generatedAt}>
              {copy.generatedAt}: {formatTimestamp(overview.generatedAt, lang)}
            </p>
          ) : null}
        </aside>
      </div>
    </section>
  );
}
