import type { AgentInstance, ChatRoomParticipant, SessionSummary } from "../api/types";

export type AgentDisplayTone = "chat" | "research" | "self" | "supervised" | "tool" | "memory" | "general";

export type AgentDisplayInfo = {
  name: string;
  functionLabel: string;
  modelLabel: string;
  tone: AgentDisplayTone;
  meta: string;
};

type AgentLike = Partial<Pick<
  AgentInstance,
  "agentId" | "agentCode" | "displayName" | "metadata" | "primaryMode" | "roleKey" | "promptTemplateId" | "llmBindings"
>>;

type SessionLike = Partial<Pick<
  SessionSummary,
  "id" | "title" | "agentCode" | "agentDisplayName" | "dialogueModelId"
>>;

type ParticipantLike = Partial<Pick<
  ChatRoomParticipant,
  "participantId" | "agentId" | "agentCode" | "title" | "teamRole" | "teamMemberPurpose"
>>;

const NOISY_LABELS = new Set([
  "new session",
  "new chat",
  "新会话",
  "新建会话",
  "untitled",
  "未命名",
  "agent",
  "main agent",
  "primary",
  "primary agent",
  "chat default",
  "chat-default",
  "prompt-chat-default",
  "default chat",
  "general chat agent",
  "general chat",
  "会话默认",
  "默认会话",
  "通用会话 agent",
  "通用会话",
  "主 agent",
  "主Agent",
  "主代理",
]);

function clean(value: unknown): string {
  return String(value ?? "").trim();
}

export function metadataString(agent: Pick<AgentInstance, "metadata"> | undefined | null, key: string): string {
  const value = agent?.metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}

function isNoisyLabel(value: unknown): boolean {
  const normalized = clean(value).toLowerCase();
  return !normalized || NOISY_LABELS.has(normalized);
}

function compactLabel(value: string): string {
  return value.replace(/^prompt-/, "").replace(/_/g, "-");
}

function compactFunctionLabel(value: string, lang: "zh" | "en"): string {
  const label = clean(value);
  if (!label) {
    return "";
  }
  const lower = label.toLowerCase();
  const normalized = lower.replace(/^prompt-/, "").replace(/[_\s]+/g, "-");
  const mapped: Record<string, { zh: string; en: string }> = {
    "chat-default": { zh: "会话入口", en: "Chat entry" },
    "default-chat": { zh: "会话入口", en: "Chat entry" },
    "general-chat-agent": { zh: "会话入口", en: "Chat entry" },
    "general-chat": { zh: "会话入口", en: "Chat entry" },
    "research-agent": { zh: "科研成员", en: "Research member" },
    "self-evolution-agent": { zh: "自进化成员", en: "Self-evolution member" },
    "supervised-evolution-agent": { zh: "监督成员", en: "Supervision member" },
    "supervised-agent": { zh: "监督成员", en: "Supervision member" },
    "knowledge-base-manager": { zh: "知识管理员", en: "Knowledge manager" },
    "knowledge-manager": { zh: "知识管理员", en: "Knowledge manager" },
    "科研-agent": { zh: "科研成员", en: "Research member" },
    "自进化-agent": { zh: "自进化成员", en: "Self-evolution member" },
    "自进化执行-agent": { zh: "执行者", en: "Executor" },
    "自进化审查-agent": { zh: "审查者", en: "Reviewer" },
    "自进化评审-agent": { zh: "审查者", en: "Reviewer" },
    "自进化总结-agent": { zh: "总结者", en: "Summarizer" },
    "监督进化-agent": { zh: "监督成员", en: "Supervision member" },
    "监督裁判-agent": { zh: "监督裁判", en: "Judge" },
    "监督审计-agent": { zh: "监督审计", en: "Auditor" },
    "监督评审-agent": { zh: "监督评审", en: "Reviewer" },
    "监督候选-agent": { zh: "监督候选", en: "Candidate" },
    "监督基线-agent": { zh: "监督基线", en: "Baseline" },
  };
  if (mapped[normalized]) {
    return mapped[normalized][lang];
  }
  if (lang === "zh") {
    return label
      .replace(/\s*Agent$/i, "")
      .replace(/\s*agent$/i, "")
      .replace(/知识库管理员/g, "知识管理员")
      .trim();
  }
  return label
    .replace(/\s*Agent$/i, "")
    .replace(/\s*agent$/i, "")
    .replace(/\bSelf-evolution\b/i, "Self-evolution")
    .trim();
}

export function compactModelLabel(value: unknown): string {
  const model = clean(value);
  if (!model) {
    return "";
  }
  return model
    .replace(/^openai\//i, "")
    .replace(/^anthropic\//i, "")
    .replace(/^deepseek\//i, "")
    .replace(/^minimax\//i, "")
    .replace(/^llamacpp\//i, "")
    .replace(/\.gguf$/i, "")
    .replace(/[_\s]+/g, "-");
}

function dialogueModelLabel(
  session: SessionLike | undefined | null,
  agent: AgentLike | undefined | null,
): string {
  return compactModelLabel(session?.dialogueModelId || agent?.llmBindings?.dialogue?.modelId);
}

function modeTone(mode: string, role = "", prompt = ""): AgentDisplayTone {
  const key = `${mode} ${role} ${prompt}`.toLowerCase();
  if (key.includes("research")) return "research";
  if (key.includes("self")) return "self";
  if (key.includes("supervised")) return "supervised";
  if (key.includes("tool")) return "tool";
  if (key.includes("memory")) return "memory";
  if (key.includes("chat")) return "chat";
  return "general";
}

export function agentRoleLabel(
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
  fallback?: {
    templateLabel?: string;
    templateId?: string;
  },
): { label: string; tone: AgentDisplayTone } {
  const mode = clean(agent?.primaryMode);
  const role = clean(agent?.roleKey);
  const prompt = clean(agent?.promptTemplateId || fallback?.templateId);
  const functional = metadataString(agent as Pick<AgentInstance, "metadata"> | undefined, "functionalDisplayName");
  const templateLabel = clean(fallback?.templateLabel);
  const tone = modeTone(mode, role, prompt);
  const lowerRole = role.toLowerCase();
  const lowerPrompt = prompt.toLowerCase();
  const lowerFunctional = functional.toLowerCase();

  if (tone === "research") {
    if (lowerRole.includes("broad") || lowerPrompt.includes("broad")) return { label: lang === "zh" ? "广域检索" : "Broad research", tone };
    if (lowerRole.includes("deep") || lowerPrompt.includes("deep")) return { label: lang === "zh" ? "深度检索" : "Deep research", tone };
    if (lowerRole.includes("review") || lowerPrompt.includes("review")) return { label: lang === "zh" ? "证据审查" : "Evidence review", tone };
    if (lowerRole.includes("theme") || lowerPrompt.includes("theme")) return { label: lang === "zh" ? "主题生成" : "Theme generation", tone };
    if (lowerRole.includes("card") || lowerPrompt.includes("card")) return { label: lang === "zh" ? "主题卡片" : "Theme card", tone };
    if (lowerRole.includes("ceo")) return { label: lang === "zh" ? "科研负责人" : "Research lead", tone };
    if (lowerRole.includes("organization") || lowerRole.includes("advisor")) return { label: lang === "zh" ? "科研组织顾问" : "Research advisor", tone };
    return { label: lang === "zh" ? "科研成员" : "Research member", tone };
  }

  if (tone === "self") {
    if (lowerRole.includes("summar") || lowerFunctional.includes("总结")) return { label: lang === "zh" ? "总结者" : "Summarizer", tone };
    if (lowerRole.includes("review") || lowerFunctional.includes("审查") || lowerFunctional.includes("评审")) return { label: lang === "zh" ? "审查者" : "Reviewer", tone };
    if (lowerRole.includes("executor") || lowerRole.includes("execute") || lowerFunctional.includes("执行")) return { label: lang === "zh" ? "执行者" : "Executor", tone };
    return { label: lang === "zh" ? "自进化成员" : "Self-evolution member", tone };
  }

  if (tone === "supervised") {
    if (lowerRole.includes("baseline") || lowerFunctional.includes("基线")) return { label: lang === "zh" ? "监督基线" : "Baseline", tone };
    if (lowerRole.includes("candidate") || lowerFunctional.includes("候选")) return { label: lang === "zh" ? "监督候选" : "Candidate", tone };
    if (lowerRole.includes("audit") || lowerFunctional.includes("审计")) return { label: lang === "zh" ? "监督审计" : "Auditor", tone };
    if (lowerRole.includes("judge") || lowerFunctional.includes("裁判")) return { label: lang === "zh" ? "监督裁判" : "Judge", tone };
    if (lowerRole.includes("review") || lowerFunctional.includes("评审")) return { label: lang === "zh" ? "监督评审" : "Reviewer", tone };
    return { label: lang === "zh" ? "监督成员" : "Supervision member", tone };
  }

  if (!isNoisyLabel(functional)) return { label: compactFunctionLabel(functional, lang), tone };
  if (!isNoisyLabel(templateLabel)) return { label: compactFunctionLabel(templateLabel, lang), tone };
  if (role) return { label: compactFunctionLabel(compactLabel(role), lang), tone };
  if (prompt) return { label: compactFunctionLabel(compactLabel(prompt), lang), tone };
  return { label: lang === "zh" ? "会话入口" : "Chat entry", tone: tone === "general" ? "chat" : tone };
}

export function agentDisplayInfo(
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
  fallback?: {
    name?: string;
    templateLabel?: string;
    templateId?: string;
  },
): AgentDisplayInfo {
  const role = agentRoleLabel(agent, lang, fallback);
  const name = clean(agent?.displayName)
    || clean(fallback?.name)
    || clean(agent?.agentId)
    || (lang === "zh" ? "未命名 Agent" : "Unnamed Agent");
  const code = clean(agent?.agentCode);
  const modelLabel = dialogueModelLabel(null, agent);
  return {
    name,
    functionLabel: role.label,
    modelLabel,
    tone: role.tone,
    meta: [role.label, modelLabel, code].filter(Boolean).join(" · "),
  };
}

export function sessionAgentDisplayInfo(
  session: SessionLike,
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
): AgentDisplayInfo {
  const info = agentDisplayInfo(
    agent,
    lang,
    {
      name: clean(session.agentDisplayName) || clean(session.title) || clean(session.id),
    },
  );
  const modelLabel = dialogueModelLabel(session, agent);
  return {
    ...info,
    modelLabel,
    meta: [info.functionLabel, modelLabel, clean(session.agentCode || agent?.agentCode)].filter(Boolean).join(" · "),
  };
}

export function participantAgentDisplayInfo(
  participant: ParticipantLike,
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
): AgentDisplayInfo {
  const teamRole = clean(participant.teamMemberPurpose) || clean(participant.teamRole);
  if (teamRole) {
    const name = clean(agent?.displayName) || clean(participant.title) || clean(participant.participantId);
    const code = clean(participant.agentCode || agent?.agentCode);
    const base = agentDisplayInfo(agent, lang, {
      name,
    });
    return {
      name: base.name,
      functionLabel: teamRole,
      modelLabel: base.modelLabel,
      tone: base.tone,
      meta: [teamRole, base.modelLabel, code].filter(Boolean).join(" · "),
    };
  }
  return agentDisplayInfo(
    agent,
    lang,
    {
      name: clean(agent?.displayName) || clean(participant.title) || clean(participant.participantId),
    },
  );
}
