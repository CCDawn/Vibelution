/**
 * Pure Agents presentation helpers (D3).
 * Free of React hooks and AgentsRoute-only draft helpers.
 */
import type { AgentConfigWorkspaceAgent, AgentModelChoice } from "../../api/types";
import { agentDisplayInfo } from "../agentDisplay";

export type ModelProfileChoice = {
  key: string;
  modelId: string;
  label: string;
  modelLabel: string;
  providerId: string;
  providerLabel: string;
  providerKind: string;
  unresolved?: boolean;
};

export type RuntimeFocusEvidenceResult = {
  match: import("../../api/types").AgentRuntimeEvidenceMatch | null;
  reason: "run" | "source_run" | "session" | "fallback" | "missing";
};

export function normalizeText(value: unknown) {
  return String(value ?? "").trim().toLowerCase();
}

export function formatTimestamp(value: string, lang: "zh" | "en") {
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
  }).format(parsed);
}

export function timestampValue(value: string) {
  const parsed = new Date(String(value || ""));
  return Number.isNaN(parsed.getTime()) ? 0 : parsed.getTime();
}

export function agentLabel(agent: AgentConfigWorkspaceAgent | null | undefined) {
  if (!agent) {
    return "-";
  }
  return agentDisplayInfo(agent, "zh").name || agent.agentId || "-";
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

export function encodeArrayBufferBase64(buffer: ArrayBuffer) {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  bytes.forEach((byte) => {
    binary += String.fromCharCode(byte);
  });
  return btoa(binary);
}

export function agentFunctionalLabel(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en" = "zh") {
  if (!agent) {
    return "-";
  }
  return agentDisplayInfo(agent, lang).functionLabel || "-";
}

export function agentFunctionTone(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  return agentDisplayInfo(agent, lang).tone;
}

export function agentSearchText(agent: AgentConfigWorkspaceAgent) {
  return normalizeText(
    [
      agent.agentId,
      agent.agentCode,
      agent.displayName,
      agent.primaryMode,
      agent.roleKey,
      Object.values(agent.llmBindings ?? {}).map((binding) => binding?.modelId).join(" "),
      agent.dialogueModel?.label,
      agent.dialogueModel?.model,
      agent.promptTemplateId,
      agent.toolPolicyId,
      agent.memoryPolicyId,
      agent.directSessionId,
      agent.workspacePath,
      agent.references.map((item) => `${item.kind} ${item.sourceLabel} ${item.mode} ${item.field}`).join(" "),
      agent.health.map((item) => `${item.code} ${item.title} ${item.detail}`).join(" "),
    ].join(" "),
  );
}

export function promptTemplateDisplayName(
  template: { name?: string; promptTemplateId?: string; templateId?: string; category?: string } | null | undefined,
  fallbackId: string | undefined,
  lang: "zh" | "en",
) {
  const templateId = String(template?.promptTemplateId || template?.templateId || fallbackId || "").trim();
  const name = String(template?.name || "").trim();
  if (lang !== "zh") {
    return name || templateId || "-";
  }
  const normalized = (name || templateId).trim().toLowerCase();
  const zhNames: Record<string, string> = {
    "research capability steward": "科研能力管理员",
    "research organization advisor": "科研组织顾问",
    "research ceo": "科研负责人",
    "chat default": "会话默认",
    "supervised judge": "监督裁判",
    "supervised auditor": "监督审计员",
    "supervised reviewer": "监督评审员",
    "supervised candidate": "监督候选",
    "supervised baseline": "监督基线",
    "self-evolution executor": "自进化执行者",
    "self-evolution summarizer": "自进化总结者",
    "self-evolution reviewer": "自进化审查者",
  };
  return zhNames[normalized] ?? (name || templateId || "-");
}

export function promptTemplateOptionLabel(
  template: { name?: string; promptTemplateId?: string; templateId?: string; category?: string },
  lang: "zh" | "en",
) {
  const id = String(template.promptTemplateId || template.templateId || "").trim();
  const category = String(template.category || "").trim();
  const name = promptTemplateDisplayName(template, id, lang);
  return category ? `${name} · ${category}` : name;
}

export function agentModelLabel(model: AgentModelChoice | null | undefined) {
  return String(model?.label || model?.model || model?.modelId || "").trim() || "-";
}

export function unresolvedDialogueModelIssue(agent: AgentConfigWorkspaceAgent | null | undefined) {
  return (agent?.health ?? []).find((item) => item.code === "unresolved_model_reference_dialogue");
}

export function agentDialogueModelDisplay(agent: AgentConfigWorkspaceAgent | null | undefined, lang: "zh" | "en") {
  const model = agent?.dialogueModel;
  const rawModelId = String(agent?.llmBindings?.dialogue?.modelId || "").trim();
  const unresolved = unresolvedDialogueModelIssue(agent);
  if (model) {
    return {
      label: agentModelLabel(model),
      detail: String(model.providerKind || model.apiKeyState || model.modelId || "").trim() || "-",
      unresolved: false,
    };
  }
  if (rawModelId) {
    return {
      label: rawModelId,
      detail: unresolved
        ? (lang === "zh" ? "模型库未注册" : "Model reference unresolved")
        : (lang === "zh" ? "模型详情不可用" : "Model details unavailable"),
      unresolved: Boolean(unresolved),
    };
  }
  return {
    label: "-",
    detail: lang === "zh" ? "未绑定对话模型" : "No dialogue model",
    unresolved: false,
  };
}

export function agentModelChoiceLabel(model: AgentModelChoice) {
  const label = agentModelLabel(model);
  const provider = String(model.providerKind || "").trim();
  const modelName = String(model.model || "").trim();
  return [label, provider && provider !== label ? provider : "", modelName && modelName !== label ? modelName : ""]
    .filter(Boolean)
    .join(" · ") || "-";
}

export function agentModelChoiceAllowed(model: AgentModelChoice) {
  const text = normalizeText([
    agentModelLabel(model),
    model.model,
    model.modelId,
    model.providerKind,
  ].join(" "));
  return !/\bimage\d*\b/.test(text) && !text.includes("image2");
}

export function buildAgentModelChoices(models: AgentModelChoice[]): ModelProfileChoice[] {
  return models
    .filter((model) => model.runtimeSelectable && agentModelChoiceAllowed(model))
    .map((model) => ({
      key: model.modelId,
      modelId: model.modelId,
      label: agentModelChoiceLabel(model),
      modelLabel: agentModelLabel(model),
      providerId: model.providerId,
      providerLabel: model.providerLabel,
      providerKind: model.providerKind,
    }))
    .sort((left, right) => left.label.localeCompare(right.label) || left.modelId.localeCompare(right.modelId));
}
