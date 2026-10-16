import type { ConversationMessage } from "../../api/types";
import { formatTurnTokenCount } from "../../components/conversation/conversationTurnUsageLabel";
import { assistantFinalAnswerText, assistantTurnIsInFlight } from "../chatTurnProtocol";

export const CHAT_RIGHT_RAIL_LAUNCHER_KINDS = [
  "side",
  "review",
  "terminal",
  "browser",
  "devtools",
  "project_tasks",
  "project_git",
  "project_notices",
] as const;

export const CHAT_RIGHT_RAIL_CONTEXT_KINDS = [
  "file",
  "subagent",
  "directory",
  "plan",
  "workflow",
  "trajectory",
  "bash",
] as const;

export const CHAT_RIGHT_RAIL_KINDS = [
  ...CHAT_RIGHT_RAIL_LAUNCHER_KINDS,
  ...CHAT_RIGHT_RAIL_CONTEXT_KINDS,
] as const;

export type ChatRightRailKind = (typeof CHAT_RIGHT_RAIL_KINDS)[number];

const SINGLETON_KINDS = new Set<ChatRightRailKind>([
  "side",
  "review",
  "terminal",
  "browser",
  "devtools",
  "directory",
  "project_tasks",
  "project_git",
  "project_notices",
]);

export const CHAT_RIGHT_RAIL_CLOSED_CAP = 8;

export type ChatRightRailTab = {
  id: string;
  kind: ChatRightRailKind;
  title: string;
  childSessionId?: string;
  targetId?: string;
  filePath?: string;
  url?: string;
  /** Current composer draft, retained independently for each side-chat tab. */
  draft?: string;
  /** Increments whenever the draft changes, so late send callbacks cannot clear newer edits. */
  draftRevision?: number;
  sendDraft?: boolean;
  /** Monotonic accepted-send generation used to reject stale readback callbacks. */
  submissionGeneration?: number;
  /** Latest accepted generation that still requires an authoritative detail readback. */
  pendingReadbackGeneration?: number;
  /** `center` draws this tab in the top session bar. Missing means the right rail. */
  host?: "rail" | "center";
};

export type ChatRightRailModel = {
  tabs: ChatRightRailTab[];
  activeId: string | null;
  closed: ChatRightRailTab[];
  reviewAutoOpened: boolean;
};

export const EMPTY_CHAT_RIGHT_RAIL: ChatRightRailModel = {
  tabs: [],
  activeId: null,
  closed: [],
  reviewAutoOpened: false,
};

export type ChatRightRailOpenInput = {
  id?: string;
  kind: ChatRightRailKind;
  title?: string;
  childSessionId?: string;
  targetId?: string;
  filePath?: string;
  url?: string;
  host?: "rail" | "center";
};

const KIND_LABELS: Record<ChatRightRailKind, { zh: string; en: string }> = {
  side: { zh: "辅助对话", en: "Side chat" },
  review: { zh: "审查", en: "Review" },
  terminal: { zh: "终端", en: "Terminal" },
  browser: { zh: "浏览器", en: "Browser" },
  devtools: { zh: "开发者工具", en: "Developer tools" },
  file: { zh: "代码查看", en: "Code" },
  subagent: { zh: "子智能体", en: "Subagent" },
  directory: { zh: "子智能体目录", en: "Subagents" },
  plan: { zh: "计划", en: "Plan" },
  workflow: { zh: "工作流实例", en: "Workflow" },
  trajectory: { zh: "模型调用轨迹", en: "Model calls" },
  bash: { zh: "后台输出", en: "Background output" },
  project_tasks: { zh: "任务", en: "Tasks" },
  project_git: { zh: "变更", en: "Changes" },
  project_notices: { zh: "通知", en: "Notifications" },
};

const CONTEXT_TITLE_KINDS = new Set<ChatRightRailKind>([
  "file",
  "subagent",
  "directory",
  "plan",
  "workflow",
  "trajectory",
  "bash",
]);

export function chatRightRailLauncherKinds(sessionKind: string | undefined): ChatRightRailKind[] {
  // Group rooms have no parent session for side chats; review, terminal,
  // browser and devtools stay available.
  if (sessionKind === "child" || sessionKind === "group") {
    return CHAT_RIGHT_RAIL_LAUNCHER_KINDS.filter((kind) => kind !== "side");
  }
  return [...CHAT_RIGHT_RAIL_LAUNCHER_KINDS];
}

export function chatRightRailKindLabel(kind: ChatRightRailKind, lang: "zh" | "en"): string {
  return KIND_LABELS[kind][lang];
}

export function chatRightRailTabLabel(tab: ChatRightRailTab, lang: "zh" | "en"): string {
  if ((CONTEXT_TITLE_KINDS.has(tab.kind) || tab.kind === "side") && tab.title.trim()) {
    return tab.title.trim();
  }
  return chatRightRailKindLabel(tab.kind, lang);
}

export function activeChatRightRailTab(model: ChatRightRailModel): ChatRightRailTab | null {
  return model.tabs.find((tab) => tab.id === model.activeId) ?? null;
}

function tabIdentity(input: ChatRightRailOpenInput): string {
  const explicit = input.id?.trim();
  if (explicit) {
    return explicit;
  }
  if (SINGLETON_KINDS.has(input.kind)) {
    return input.kind;
  }
  const key = (input.targetId || input.filePath || input.url || "").trim();
  return key ? `${input.kind}:${key}` : `${input.kind}:open`;
}

export function openChatRightRailTab(
  model: ChatRightRailModel,
  input: ChatRightRailOpenInput,
): ChatRightRailModel {
  const id = tabIdentity(input);
  const existing = model.tabs.find((tab) => tab.id === id);
  const recentlyClosed = model.closed.find((tab) => tab.id === id);
  const retained = existing ?? recentlyClosed;
  const title = (input.title || retained?.title || chatRightRailKindLabel(input.kind, "zh")).trim();
  const retainedSideState = input.kind === "side" && retained?.kind === "side" ? retained : undefined;
  const host = input.host ?? retained?.host;
  const tab: ChatRightRailTab = {
    id,
    kind: input.kind,
    title,
    childSessionId: input.childSessionId ?? retained?.childSessionId,
    targetId: input.targetId ?? retained?.targetId,
    filePath: input.filePath ?? retained?.filePath,
    url: input.url !== undefined ? input.url : retained?.url,
    ...(host === "center" ? { host } : {}),
    ...(retainedSideState ? {
      draft: retainedSideState.draft,
      draftRevision: retainedSideState.draftRevision,
      sendDraft: retainedSideState.sendDraft,
      submissionGeneration: retainedSideState.submissionGeneration,
      pendingReadbackGeneration: retainedSideState.pendingReadbackGeneration,
    } : {}),
  };
  const tabs = existing
    ? model.tabs.map((item) => (item.id === id ? tab : item))
    : [...model.tabs, tab];
  return {
    ...model,
    tabs,
    activeId: id,
    closed: model.closed.filter((item) => item.id !== id),
  };
}

export function closeChatRightRailTab(model: ChatRightRailModel, id: string): ChatRightRailModel {
  const index = model.tabs.findIndex((tab) => tab.id === id);
  if (index < 0) {
    return model;
  }
  const tab = model.tabs[index];
  const tabs = model.tabs.filter((item) => item.id !== id);
  const closed = [tab, ...model.closed.filter((item) => item.id !== id)].slice(0, CHAT_RIGHT_RAIL_CLOSED_CAP);
  const activeId = model.activeId === id
    ? (tabs[index]?.id ?? tabs[index - 1]?.id ?? null)
    : model.activeId;
  return { ...model, tabs, activeId, closed };
}

export function closeOtherChatRightRailTabs(
  model: ChatRightRailModel,
  keepId: string,
): ChatRightRailModel {
  if (!model.tabs.some((tab) => tab.id === keepId)) {
    return model;
  }
  const closing = model.tabs.filter((tab) => tab.id !== keepId);
  if (closing.length === 0) {
    return model;
  }
  let next = model;
  for (const tab of closing) {
    next = closeChatRightRailTab(next, tab.id);
  }
  return next.activeId === keepId ? next : { ...next, activeId: keepId };
}

export function closeAllChatRightRailTabs(model: ChatRightRailModel): ChatRightRailModel {
  let next = model;
  for (const tab of model.tabs) {
    next = closeChatRightRailTab(next, tab.id);
  }
  return next;
}

export function reorderChatRightRailTab(
  model: ChatRightRailModel,
  movingId: string,
  overId: string,
): ChatRightRailModel {
  if (!movingId || movingId === overId) {
    return model;
  }
  const from = model.tabs.findIndex((tab) => tab.id === movingId);
  const to = model.tabs.findIndex((tab) => tab.id === overId);
  if (from < 0 || to < 0) {
    return model;
  }
  const tabs = [...model.tabs];
  const [moved] = tabs.splice(from, 1);
  if (!moved) {
    return model;
  }
  tabs.splice(to, 0, moved);
  return { ...model, tabs };
}

export function setChatRightRailTabHost(
  model: ChatRightRailModel,
  id: string,
  host: "rail" | "center",
): ChatRightRailModel {
  const tab = model.tabs.find((item) => item.id === id);
  if (!tab) {
    return model;
  }
  if ((tab.host ?? "rail") === host && model.activeId === id) {
    return model;
  }
  return {
    ...model,
    activeId: id,
    tabs: model.tabs.map((item) => {
      if (item.id !== id) {
        return item;
      }
      if (host === "rail") {
        const next = { ...item };
        delete next.host;
        return next;
      }
      return { ...item, host };
    }),
  };
}

export function searchChatRightRailTabs(model: ChatRightRailModel, query: string): {
  open: ChatRightRailTab[];
  closed: ChatRightRailTab[];
} {
  const needle = query.trim().toLowerCase();
  const matches = (tab: ChatRightRailTab) => {
    if (!needle) {
      return true;
    }
    return [tab.title, tab.kind, tab.filePath || "", tab.targetId || ""].some((value) => (
      value.toLowerCase().includes(needle)
    ));
  };
  return {
    open: model.tabs.filter(matches),
    closed: model.closed.filter(matches),
  };
}

export function noteReviewAutoOpen(
  model: ChatRightRailModel,
  title: string,
): { model: ChatRightRailModel; opened: boolean } {
  if (model.reviewAutoOpened) {
    return { model, opened: false };
  }
  const marked = { ...model, reviewAutoOpened: true };
  if (model.tabs.some((tab) => tab.kind === "review")) {
    return { model: marked, opened: false };
  }
  const opened = openChatRightRailTab(marked, { kind: "review", title });
  if (model.tabs.length > 0) {
    return { model: { ...opened, activeId: model.activeId }, opened: true };
  }
  return { model: opened, opened: true };
}

function sideOrdinal(id: string): number {
  if (id === "side") {
    return 1;
  }
  const match = /^side:(\d+)$/.exec(id);
  return match ? Number(match[1]) : 0;
}

export function openFreshChatRightRailSideTab(
  model: ChatRightRailModel,
  input: { titleBase: string; draft?: string; sendDraft?: boolean },
): ChatRightRailModel {
  const used = [...model.tabs, ...model.closed].reduce(
    (max, tab) => Math.max(max, sideOrdinal(tab.id)),
    0,
  );
  const ordinal = used + 1;
  const id = ordinal === 1 ? "side" : `side:${ordinal}`;
  const draft = (input.draft || "").trim();
  const tab: ChatRightRailTab = {
    id,
    kind: "side",
    title: ordinal === 1 ? input.titleBase : `${input.titleBase} ${ordinal}`,
    ...(draft ? { draft, sendDraft: Boolean(input.sendDraft) } : {}),
  };
  return {
    ...model,
    tabs: [...model.tabs, tab],
    activeId: id,
    closed: model.closed.filter((item) => item.id !== id),
  };
}

export function consumeChatRightRailSideDraft(
  model: ChatRightRailModel,
  tabId: string,
): ChatRightRailModel {
  const target = tabId.trim();
  if (!target) {
    return model;
  }
  let changed = false;
  const consume = (tab: ChatRightRailTab) => {
    if (tab.id !== target || !tab.sendDraft) {
      return tab;
    }
    changed = true;
    return { ...tab, sendDraft: undefined };
  };
  const tabs = model.tabs.map(consume);
  const closed = model.closed.map(consume);
  return changed ? { ...model, tabs, closed } : model;
}

export function updateChatRightRailSideDraft(
  model: ChatRightRailModel,
  tabId: string,
  draft: string,
  expectedRevision?: number,
): ChatRightRailModel {
  const target = tabId.trim();
  if (!target) {
    return model;
  }
  let changed = false;
  const update = (tab: ChatRightRailTab) => {
    if (tab.id !== target || tab.kind !== "side") {
      return tab;
    }
    const revision = tab.draftRevision ?? 0;
    if ((expectedRevision !== undefined && revision !== expectedRevision) || tab.draft === draft) {
      return tab;
    }
    changed = true;
    return { ...tab, draft: draft || undefined, draftRevision: revision + 1 };
  };
  const tabs = model.tabs.map(update);
  const closed = model.closed.map(update);
  return changed ? { ...model, tabs, closed } : model;
}

export function trackChatRightRailSideSubmission(
  model: ChatRightRailModel,
  tabId: string,
): ChatRightRailModel {
  const target = tabId.trim();
  if (!target) {
    return model;
  }
  let changed = false;
  const update = (tab: ChatRightRailTab) => {
    if (tab.id !== target || tab.kind !== "side") {
      return tab;
    }
    const generation = (tab.submissionGeneration ?? 0) + 1;
    changed = true;
    return {
      ...tab,
      submissionGeneration: generation,
      pendingReadbackGeneration: generation,
    };
  };
  const tabs = model.tabs.map(update);
  const closed = model.closed.map(update);
  return changed ? { ...model, tabs, closed } : model;
}

export function confirmChatRightRailSideReadback(
  model: ChatRightRailModel,
  tabId: string,
  generation: number,
): ChatRightRailModel {
  const target = tabId.trim();
  if (!target || !Number.isSafeInteger(generation) || generation <= 0) {
    return model;
  }
  let changed = false;
  const update = (tab: ChatRightRailTab) => {
    if (tab.id !== target || tab.kind !== "side") {
      return tab;
    }
    if (tab.pendingReadbackGeneration !== generation) {
      return tab;
    }
    changed = true;
    return { ...tab, pendingReadbackGeneration: undefined };
  };
  const tabs = model.tabs.map(update);
  const closed = model.closed.map(update);
  return changed ? { ...model, tabs, closed } : model;
}

export function rememberChatRightRailSideChild(
  model: ChatRightRailModel,
  tabId: string,
  childSessionId: string,
): ChatRightRailModel {
  const id = childSessionId.trim();
  const target = tabId.trim();
  if (!id || !target) {
    return model;
  }
  let changed = false;
  const bind = (tab: ChatRightRailTab) => {
    if (tab.id !== target || tab.kind !== "side" || tab.childSessionId === id) {
      return tab;
    }
    changed = true;
    return { ...tab, childSessionId: id, targetId: id, sendDraft: undefined };
  };
  const tabs = model.tabs.map(bind);
  const closed = model.closed.map(bind);
  return changed ? {
    ...model,
    tabs,
    closed,
  } : model;
}

export function normalizeChatRightRailBrowserUrl(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) {
    return null;
  }
  const withProtocol = /^[a-z][a-z0-9+.-]*:/i.test(trimmed) ? trimmed : `https://${trimmed}`;
  let url: URL;
  try {
    url = new URL(withProtocol);
  } catch {
    return null;
  }
  if ((url.protocol !== "http:" && url.protocol !== "https:") || !url.hostname) {
    return null;
  }
  return url.toString();
}

export type ChatRightRailDevtoolsInput = {
  phase?: string;
  status?: string;
  messages?: readonly ConversationMessage[];
} | null | undefined;

export type ChatRightRailDevtoolsRow = {
  id: "phase" | "status" | "messages" | "toolCalls" | "tokens";
  labelZh: string;
  labelEn: string;
  value: string;
};

export function projectChatRightRailDevtools(
  input: ChatRightRailDevtoolsInput,
  lang: "zh" | "en" = "zh",
): {
  empty: boolean;
  rows: ChatRightRailDevtoolsRow[];
} {
  if (!input) {
    return { empty: true, rows: [] };
  }
  const messages = input.messages ?? [];
  let toolCalls = 0;
  let tokens = 0;
  let sawTokens = false;
  for (const message of messages) {
    if (message.role !== "assistant") {
      continue;
    }
    for (const item of message.turnItems ?? []) {
      if (item.type === "tool_call") {
        toolCalls += 1;
      }
    }
    const total = message.usageStats?.totalTokens;
    if (typeof total === "number" && Number.isFinite(total)) {
      tokens += total;
      sawTokens = true;
    }
  }
  const dash = "—";
  return {
    empty: false,
    rows: [
      { id: "phase", labelZh: "阶段", labelEn: "Phase", value: input.phase?.trim() || dash },
      { id: "status", labelZh: "状态", labelEn: "Status", value: input.status?.trim() || dash },
      { id: "messages", labelZh: "消息", labelEn: "Messages", value: String(messages.length) },
      { id: "toolCalls", labelZh: "工具调用", labelEn: "Tool calls", value: String(toolCalls) },
      { id: "tokens", labelZh: "Token", labelEn: "Tokens", value: sawTokens ? formatTurnTokenCount(tokens, lang) : dash },
    ],
  };
}

export type ChatRightRailTranscriptLine = {
  id: string;
  role: "user" | "assistant";
  text: string;
  pending: boolean;
};

export function chatRightRailTranscriptLines(
  messages: readonly ConversationMessage[],
): ChatRightRailTranscriptLine[] {
  const lines: ChatRightRailTranscriptLine[] = [];
  messages.forEach((message, index) => {
    if (message.role === "user") {
      const text = message.content.trim();
      if (text) {
        lines.push({ id: message.id || `user-${index}`, role: "user", text, pending: false });
      }
      return;
    }
    const text = assistantFinalAnswerText(message).trim();
    const pending = assistantTurnIsInFlight(message);
    if (!text && !pending) {
      return;
    }
    lines.push({
      id: message.id || `assistant-${index}`,
      role: "assistant",
      text,
      pending,
    });
  });
  return lines;
}
