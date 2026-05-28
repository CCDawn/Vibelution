import type { AgentInstance, ChatRoomParticipant, SessionSummary } from "../api/types";

export type AgentDisplayTone = "chat" | "research" | "self" | "supervised" | "tool" | "memory" | "general";

export type AgentDisplayInfo = {
  name: string;
  functionLabel: string;
  tone: AgentDisplayTone;
  meta: string;
};

type AgentLike = Partial<Pick<
  AgentInstance,
  "agentId" | "agentCode" | "displayName" | "metadata" | "primaryMode" | "roleKey" | "profileId" | "templateId" | "promptTemplateId"
>>;

type SessionLike = Partial<Pick<
  SessionSummary,
  "id" | "title" | "agentCode" | "agentDisplayName" | "agentProfileId" | "agentTemplateId" | "agentTemplateLabel"
>>;

type ParticipantLike = Partial<Pick<
  ChatRoomParticipant,
  "participantId" | "agentId" | "agentCode" | "title" | "agentProfileId" | "agentTemplateId" | "agentTemplateLabel"
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
    profileId?: string;
    templateId?: string;
  },
): { label: string; tone: AgentDisplayTone } {
  const mode = clean(agent?.primaryMode);
  const role = clean(agent?.roleKey);
  const prompt = clean(agent?.promptTemplateId || fallback?.templateId || agent?.templateId);
  const profile = clean(agent?.profileId || fallback?.profileId);
  const functional = metadataString(agent as Pick<AgentInstance, "metadata"> | undefined, "functionalDisplayName");
  const templateLabel = clean(fallback?.templateLabel);
  const tone = modeTone(mode, role, prompt);
  const lowerRole = role.toLowerCase();
  const lowerPrompt = prompt.toLowerCase();
  const lowerProfile = profile.toLowerCase();

  if (tone === "research") {
    if (lowerRole.includes("broad") || lowerPrompt.includes("broad") || lowerProfile.includes("broad")) return { label: lang === "zh" ? "广搜 Agent" : "Broad research", tone };
    if (lowerRole.includes("deep") || lowerPrompt.includes("deep") || lowerProfile.includes("deep")) return { label: lang === "zh" ? "深搜 Agent" : "Deep research", tone };
    if (lowerRole.includes("review") || lowerPrompt.includes("review") || lowerProfile.includes("review")) return { label: lang === "zh" ? "证据审查 Agent" : "Evidence review", tone };
    if (lowerRole.includes("theme") || lowerPrompt.includes("theme") || lowerProfile.includes("theme")) return { label: lang === "zh" ? "主题生成 Agent" : "Theme generation", tone };
    if (lowerRole.includes("card") || lowerPrompt.includes("card") || lowerProfile.includes("card")) return { label: lang === "zh" ? "主题卡 Agent" : "Theme card", tone };
    if (lowerRole.includes("ceo")) return { label: lang === "zh" ? "科研负责人" : "Research lead", tone };
    if (lowerRole.includes("organization") || lowerRole.includes("advisor")) return { label: lang === "zh" ? "科研组织顾问" : "Research advisor", tone };
    return { label: lang === "zh" ? "科研 Agent" : "Research Agent", tone };
  }

  if (tone === "self") {
    if (lowerRole.includes("summar")) return { label: lang === "zh" ? "自进化总结 Agent" : "Self-evolution summarizer", tone };
    if (lowerRole.includes("review")) return { label: lang === "zh" ? "自进化审查 Agent" : "Self-evolution reviewer", tone };
    if (lowerRole.includes("executor") || lowerRole.includes("execute")) return { label: lang === "zh" ? "自进化执行 Agent" : "Self-evolution executor", tone };
    return { label: lang === "zh" ? "自进化 Agent" : "Self-evolution Agent", tone };
  }

  if (tone === "supervised") {
    if (lowerRole.includes("baseline")) return { label: lang === "zh" ? "监督基线 Agent" : "Supervised baseline", tone };
    if (lowerRole.includes("candidate")) return { label: lang === "zh" ? "监督候选 Agent" : "Supervised candidate", tone };
    if (lowerRole.includes("review")) return { label: lang === "zh" ? "监督评审 Agent" : "Supervised reviewer", tone };
    return { label: lang === "zh" ? "监督进化 Agent" : "Supervised evolution", tone };
  }

  if (!isNoisyLabel(functional)) return { label: functional, tone };
  if (!isNoisyLabel(templateLabel)) return { label: templateLabel, tone };
  if (role) return { label: compactLabel(role), tone };
  if (prompt) return { label: compactLabel(prompt), tone };
  if (!isNoisyLabel(profile)) return { label: compactLabel(profile), tone };
  return { label: lang === "zh" ? "通用会话 Agent" : "General chat Agent", tone: tone === "general" ? "chat" : tone };
}

export function agentDisplayInfo(
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
  fallback?: {
    name?: string;
    templateLabel?: string;
    profileId?: string;
    templateId?: string;
  },
): AgentDisplayInfo {
  const role = agentRoleLabel(agent, lang, fallback);
  const name = clean(agent?.displayName)
    || clean(fallback?.name)
    || clean(agent?.agentId)
    || (lang === "zh" ? "未命名 Agent" : "Unnamed Agent");
  const code = clean(agent?.agentCode);
  return {
    name,
    functionLabel: role.label,
    tone: role.tone,
    meta: [role.label, code].filter(Boolean).join(" · "),
  };
}

export function sessionAgentDisplayInfo(
  session: SessionLike,
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
): AgentDisplayInfo {
  return agentDisplayInfo(
    agent,
    lang,
    {
      name: clean(session.agentDisplayName) || clean(session.title) || clean(session.id),
      templateLabel: session.agentTemplateLabel,
      profileId: session.agentProfileId,
      templateId: session.agentTemplateId,
    },
  );
}

export function participantAgentDisplayInfo(
  participant: ParticipantLike,
  agent: AgentLike | undefined | null,
  lang: "zh" | "en",
): AgentDisplayInfo {
  return agentDisplayInfo(
    agent,
    lang,
    {
      name: clean(agent?.displayName) || clean(participant.title) || clean(participant.participantId),
      templateLabel: participant.agentTemplateLabel,
      profileId: participant.agentProfileId,
      templateId: participant.agentTemplateId,
    },
  );
}
