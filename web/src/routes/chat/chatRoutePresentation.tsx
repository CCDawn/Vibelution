import type {
  AgentInstance,
  ChatRoomMessage,
  ChatRoomMode,
  ChatRoomParticipant,
  ChatRoomPurpose,
  SessionCacheCompositionSegment,
} from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import styles from "../ChatCodingRoute.styles";

export function chatRoomModeLabel(mode: ChatRoomMode, lang: "zh" | "en") {
  if (mode.id === "round_robin") {
    return lang === "zh" ? "轮询讨论" : "Round robin";
  }
  if (mode.id === "opportunistic") {
    return lang === "zh" ? "抢占式讨论" : "Opportunistic";
  }
  if (mode.id === "medical_consultation_panel") {
    return lang === "zh" ? "协同问诊会诊" : "Medical consultation";
  }
  return mode.label || mode.id;
}


export function chatRoomPurposeLabel(purpose: ChatRoomPurpose, lang: "zh" | "en") {
  if (purpose.id === "chat") {
    return lang === "zh" ? "聊天" : "Chat";
  }
  if (purpose.id === "discussion") {
    return lang === "zh" ? "讨论" : "Discussion";
  }
  if (purpose.id === "meeting") {
    return lang === "zh" ? "会议" : "Meeting";
  }
  if (purpose.id === "medical_triage") {
    return lang === "zh" ? "医疗分诊建议" : "Medical triage";
  }
  return purpose.label || purpose.id;
}


export function contextCompositionSegmentClass(key: string) {
  switch (key) {
    case "current_user":
      return styles.contextCompositionSegmentUser;
    case "history":
      return styles.contextCompositionSegmentHistory;
    case "active_task":
      return styles.contextCompositionSegmentTask;
    case "agent_context":
      return styles.contextCompositionSegmentAgent;
    case "guidance":
      return styles.contextCompositionSegmentGuidance;
    case "skill":
    case "active_skill":
      return styles.contextCompositionSegmentSkill;
    case "attachments":
      return styles.contextCompositionSegmentAttachments;
    default:
      return styles.contextCompositionSegmentOther;
  }
}


export function contextCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `contextSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}


export function cacheCompositionSegmentLabel(key: string, fallback: string, t: (key: TranslationKey) => string) {
  const dictionaryKey = `cacheSegment_${key}` as TranslationKey;
  const translated = t(dictionaryKey);
  return translated === dictionaryKey ? (fallback || key) : translated;
}


export function promptSegmentDisplayLabel(
  segment: Pick<SessionCacheCompositionSegment, "key" | "label" | "promptCategory">,
  lang: "zh" | "en",
  t: (key: TranslationKey) => string,
) {
  const key = (segment.key || "").trim();
  switch (key) {
    case "system_prompt":
    case "system_prompt_overhead":
      return lang === "zh" ? "系统提示词" : "system prompt";
    case "agent_protocol":
      return lang === "zh" ? "Agent 规范" : "agent protocol";
    case "tool_descriptions":
      return lang === "zh" ? "工具描述" : "tool descriptions";
    case "tool_schema":
      return lang === "zh" ? "工具 schema" : "tool schema";
    case "provider_unmapped":
      return lang === "zh" ? "Provider 未映射" : "provider unmapped";
    case "agent_runtime":
      return lang === "zh" ? "Agent 运行规范" : "agent runtime rules";
    case "prompt_template":
      return lang === "zh" ? "Agent 提示模板" : "agent prompt template";
    case "project_rules":
      return lang === "zh" ? "项目规范" : "project rules";
    case "research_organization":
      return lang === "zh" ? "研究组织上下文" : "research organization context";
    case "project_agent_registry":
      return lang === "zh" ? "Agent registry" : "agent registry";
    case "agent_messages":
      return lang === "zh" ? "Agent 消息" : "agent messages";
    case "provider_extra_hit":
      return lang === "zh" ? "厂商额外命中" : "provider extra";
    default:
      return contextCompositionSegmentLabel(key, segment.label || key, t);
  }
}


export function cacheCalibrationSummaryLabel(
  status: string,
  reason: string,
  overestimatedTokens: number,
  extraCachedTokens: number,
  numberFormatter: Intl.NumberFormat,
  lang: "zh" | "en",
) {
  const normalizedStatus = (status || "").trim();
  const normalizedReason = (reason || "").trim();
  const providerName = /xiaomi|mimo/i.test(normalizedReason)
    ? "Xiaomi/MiMo"
    : /qwen/i.test(normalizedReason)
      ? "Qwen"
      : /openai|gpt/i.test(normalizedReason)
        ? "OpenAI"
        : lang === "zh" ? "厂商" : "provider";
  if (normalizedStatus === "aligned") {
    return lang === "zh" ? `${providerName} 真实命中与稳定前缀上界一致` : `${providerName} observed hits match the stable-prefix upper bound`;
  }
  if (normalizedStatus === "not_available") {
    return lang === "zh" ? "厂商没有返回真实缓存字段，本面板仅展示稳定前缀上界" : "Provider cache fields were not returned; showing stable-prefix upper bound only";
  }
  if (overestimatedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 真实命中低于稳定前缀上界，上界未兑现 ${numberFormatter.format(overestimatedTokens)} tokens`
      : `${providerName} observed hits are below the stable-prefix upper bound by ${numberFormatter.format(overestimatedTokens)} tokens`;
  }
  if (extraCachedTokens > 0) {
    return lang === "zh"
      ? `${providerName} 返回了上界分段外的额外命中 ${numberFormatter.format(extraCachedTokens)} tokens`
      : `${providerName} reported ${numberFormatter.format(extraCachedTokens)} extra cached tokens outside upper-bound segments`;
  }
  return lang === "zh" ? "已按厂商返回的真实缓存字段校准" : "Calibrated with provider-reported cache fields";
}



export function formatAgentIdentityLabel(name: string, fallback = "Agent") {
  return String(name || fallback || "Agent").trim() || "Agent";
}


export function compactAgentRoleLabel(role: string, fallback = "") {
  const cleanRole = String(role || "").trim();
  if (!cleanRole) {
    return String(fallback || "").trim();
  }
  const beforeSlash = cleanRole.split("/")[0]?.trim() || cleanRole;
  const beforePunctuation = beforeSlash.split(/[，,。；;：:]/)[0]?.trim() || beforeSlash;
  return beforePunctuation.length > 14 ? `${beforePunctuation.slice(0, 14)}...` : beforePunctuation;
}


export function shouldCollapseGroupMessage(content: string) {
  const text = String(content || "").trim();
  return text.length > 260 || text.split(/\r?\n/).length > 8;
}


export function groupConsecutiveBy<T>(items: readonly T[], keyOf: (item: T) => string): T[][] {
  const groups: T[][] = [];
  for (const item of items) {
    const key = String(keyOf(item) ?? "").trim();
    const current = groups.at(-1);
    const currentKey = current ? String(keyOf(current[0]) ?? "").trim() : "";
    if (current && currentKey && currentKey === key) {
      current.push(item);
      continue;
    }
    groups.push([item]);
  }
  return groups;
}


export function shouldDefaultCollapseGroupMessage(message: ChatRoomMessage) {
  return message.audience === "internal" || message.visibility === "collapsed_by_default";
}


export function agentRoleClass(tone: string) {
  return `agentRoleTag_${tone}`;
}


export function avatarInitials(agentCode?: string, name?: string, fallback = "AI") {
  const code = String(agentCode ?? "").trim();
  const numericTail = code.match(/\d{2,}$/)?.[0];
  if (numericTail) {
    return numericTail.slice(-2);
  }
  const compactCode = code.replace(/[^A-Za-z0-9]/g, "");
  if (compactCode && compactCode.length <= 3) {
    return compactCode.slice(0, 2).toUpperCase();
  }
  const title = String(name ?? "").trim();
  return title.slice(0, 2) || fallback;
}


export function avatarImageUrlFrom(...sources: unknown[]) {
  for (const source of sources) {
    if (!source || typeof source !== "object") {
      continue;
    }
    const record = source as { avatarImageUrl?: unknown; agentAvatarImageUrl?: unknown };
    const url = String(record.avatarImageUrl ?? record.agentAvatarImageUrl ?? "").trim();
    if (url) {
      return url;
    }
  }
  return "";
}


export function imageInputModelIdForAgent(agent: AgentInstance | undefined, fallbackDialogueModelId = "") {
  const visionModelId = String(agent?.llmBindings?.vision?.modelId ?? "").trim();
  if (visionModelId) {
    return visionModelId;
  }
  const dialogueModelId = String(agent?.llmBindings?.dialogue?.modelId ?? "").trim();
  return dialogueModelId || String(fallbackDialogueModelId || "").trim();
}


export function modelImageInputSupport(
  supportByModelId: Map<string, boolean | null>,
  modelId: string,
): boolean | null {
  const normalizedModelId = String(modelId || "").trim();
  if (!normalizedModelId || !supportByModelId.has(normalizedModelId)) {
    return null;
  }
  const support = supportByModelId.get(normalizedModelId);
  return typeof support === "boolean" ? support : null;
}


export function conversationMetadataText(metadata: Record<string, unknown> | undefined, key: string) {
  const value = metadata?.[key];
  return typeof value === "string" ? value.trim() : "";
}


export function renderAgentAvatar(className: string, imageUrl: string | undefined, fallback: string) {
  return (
    <span className={className} aria-hidden="true">
      {imageUrl ? <img src={imageUrl} alt="" className={styles.agentAvatarImage} /> : fallback}
    </span>
  );
}


export function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}


export function stripGroupSpeakerPrefix(message: ChatRoomMessage, identityName = "") {
  let content = String(message.content || message.summary || "").trim();
  if (!content) {
    return "";
  }
  const code = String(message.speakerCode ?? "").trim();
  const labels = [
    message.speakerTitle,
    identityName,
    code,
  ]
    .map((item) => String(item ?? "").trim())
    .filter(Boolean);
  labels.forEach((label) => {
    content = content.replace(new RegExp(`^\\s*${escapeRegExp(label)}\\s*[:：]\\s*`), "").trim();
  });
  if (code) {
    content = content.replace(
      new RegExp(`^\\s*${escapeRegExp(code)}\\s*[·\\-]\\s*[^\\n:：]{1,40}\\s*[:：]\\s*`),
      "",
    ).trim();
  }
  return content;
}


export function isAvailableGroupParticipant(participant: ChatRoomParticipant) {
  return !participant.agentMissing && participant.enabled !== false;
}
