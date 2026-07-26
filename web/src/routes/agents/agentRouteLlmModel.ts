/**
 * Pure Agents LLM binding / reasoning helpers (D3).
 */
import type {
  AgentConfigWorkspace,
  AgentConfigWorkspaceAgent,
  AgentLlmBindings,
  AgentLlmSlotDefinition,
  AgentModelChoice,
} from "../../api/types";
import type { AgentConfigDraft } from "../AgentCoreConfigPanel";

export const FALLBACK_AGENT_LLM_SLOTS: AgentLlmSlotDefinition[] = [
  {
    slot: "dialogue",
    label: "对话模型",
    description: "处理用户对话、工具规划和主回复生成。",
    required: true,
    requiresImageInput: false,
  },
  {
    slot: "mentalModel",
    label: "心智模型",
    description: "用于心智状态、长期偏好和自我解释相关推理。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "summary",
    label: "摘要模型",
    description: "用于会话压缩、运行摘要和交接材料整理。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "subagentPlanning",
    label: "子 Agent 规划",
    description: "用于拆解委派任务、确定子 Agent 目标和边界。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "subagentExecution",
    label: "子 Agent 执行",
    description: "用于执行被委派的窄任务和返回结构化证据。",
    required: false,
    requiresImageInput: false,
  },
  {
    slot: "vision",
    label: "视觉理解",
    description: "用于图片输入、截图分析和多模态理解。",
    required: false,
    requiresImageInput: true,
  },
];

export function agentLlmSlots(workspace: AgentConfigWorkspace | undefined): AgentLlmSlotDefinition[] {
  return workspace?.agentLlmSlots?.length ? workspace.agentLlmSlots : FALLBACK_AGENT_LLM_SLOTS;
}

/** Known protocol effort tokens; UI options still come from model contract only. */
export const AGENT_REASONING_EFFORT_VALUES = [
  "none",
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
  "max",
  "ultra",
  "off",
  "on",
] as const;

export function normalizeAgentReasoningEffort(value: unknown, allowed?: readonly string[] | null) {
  const normalized = String(value ?? "").trim().toLowerCase();
  if (!normalized) return "";
  if (allowed && allowed.length > 0) {
    return allowed.includes(normalized) ? normalized : "";
  }
  return AGENT_REASONING_EFFORT_VALUES.includes(normalized as typeof AGENT_REASONING_EFFORT_VALUES[number])
    ? normalized
    : "";
}

export function agentModelReasoningEffortValues(model: AgentModelChoice | null | undefined): string[] {
  const values = Array.isArray(model?.reasoningEffortValues) ? model.reasoningEffortValues : [];
  return values
    .map((value) => String(value || "").trim().toLowerCase())
    .filter(Boolean);
}

export function agentModelSupportsReasoningEffort(model: AgentModelChoice | null | undefined) {
  if ((model as Record<string, unknown> | null | undefined)?.supportsReasoningEffort === false) {
    return false;
  }
  return agentModelReasoningEffortValues(model).length > 0
    || Boolean((model as Record<string, unknown> | null | undefined)?.supportsReasoningEffort);
}

export function agentModelById(models: AgentModelChoice[] | null | undefined, modelId: string) {
  const normalizedModelId = String(modelId || "").trim();
  if (!normalizedModelId) {
    return undefined;
  }
  return (models ?? []).find((model) => String(model.modelId || "").trim() === normalizedModelId);
}

export function normalizeAgentLlmBindings(bindings: AgentLlmBindings | null | undefined): AgentLlmBindings {
  return Object.fromEntries(
    Object.entries(bindings ?? {})
      .map(([slot, binding]) => [slot, String(binding?.modelId ?? "").trim()])
      .filter(([, modelId]) => modelId)
      .map(([slot, modelId]) => [slot, { modelId }]),
  ) as AgentLlmBindings;
}

export function agentLlmSlotModelId(bindings: AgentLlmBindings | null | undefined, slot: AgentLlmSlotDefinition | undefined) {
  const slotKey = slot?.slot ?? "dialogue";
  return String(bindings?.[slotKey]?.modelId ?? "").trim();
}

export function updateAgentLlmSlotBinding(
  bindings: AgentLlmBindings,
  slot: AgentLlmSlotDefinition,
  modelId: string,
): AgentLlmBindings {
  const next = { ...normalizeAgentLlmBindings(bindings) };
  const normalizedModelId = String(modelId || "").trim();
  if (normalizedModelId) {
    next[slot.slot] = { modelId: normalizedModelId };
  } else {
    delete next[slot.slot];
  }
  return next;
}

export function sameAgentLlmBindings(left: AgentLlmBindings | null | undefined, right: AgentLlmBindings | null | undefined) {
  const normalizedLeft = normalizeAgentLlmBindings(left);
  const normalizedRight = normalizeAgentLlmBindings(right);
  const keys = Array.from(new Set([...Object.keys(normalizedLeft), ...Object.keys(normalizedRight)])).sort();
  return keys.every((key) => {
    const slot = key as keyof AgentLlmBindings;
    return String(normalizedLeft[slot]?.modelId ?? "") === String(normalizedRight[slot]?.modelId ?? "");
  });
}

export function normalizeAgentReasoningEffortBySlot(value: unknown): Record<string, string> {
  if (!value || typeof value !== "object") {
    return {};
  }
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .map(([slot, effort]) => [String(slot || "").trim(), normalizeAgentReasoningEffort(effort)])
      .filter(([slot, effort]) => slot && effort),
  );
}

export function agentReasoningEffortBySlot(agent: AgentConfigWorkspaceAgent | null | undefined): Record<string, string> {
  const metadata = agent?.metadata && typeof agent.metadata === "object"
    ? agent.metadata as Record<string, unknown>
    : {};
  return normalizeAgentReasoningEffortBySlot(metadata.llmReasoningEffort);
}

export function pruneAgentReasoningEffortBySlot(
  efforts: Record<string, string>,
  bindings: AgentLlmBindings,
  models: AgentModelChoice[] | null | undefined,
) {
  const normalizedBindings = normalizeAgentLlmBindings(bindings);
  return Object.fromEntries(
    Object.entries(efforts)
      .map(([slot, effort]) => {
        const slotKey = slot as keyof AgentLlmBindings;
        const modelId = String(normalizedBindings[slotKey]?.modelId || "").trim();
        const model = agentModelById(models, modelId);
        const allowed = agentModelReasoningEffortValues(model);
        if (!agentModelSupportsReasoningEffort(model) || allowed.length === 0) {
          return [slot, ""];
        }
        return [slot, normalizeAgentReasoningEffort(effort, allowed)];
      })
      .filter(([slot, effort]) => slot && effort),
  );
}

export function updateAgentReasoningEffortBySlot(efforts: Record<string, string>, slot: string, effort: string) {
  const next = { ...normalizeAgentReasoningEffortBySlot(efforts) };
  const normalizedEffort = normalizeAgentReasoningEffort(effort);
  if (normalizedEffort) {
    next[slot] = normalizedEffort;
  } else {
    delete next[slot];
  }
  return next;
}

export function sameAgentReasoningEffortBySlot(left: Record<string, string>, right: Record<string, string>) {
  const normalizedLeft = normalizeAgentReasoningEffortBySlot(left);
  const normalizedRight = normalizeAgentReasoningEffortBySlot(right);
  const keys = Array.from(new Set([...Object.keys(normalizedLeft), ...Object.keys(normalizedRight)])).sort();
  return keys.every((key) => normalizedLeft[key] === normalizedRight[key]);
}

export function agentMetadataWithReasoningEffort(draft: AgentConfigDraft, models: AgentModelChoice[] | null | undefined) {
  const metadata: Record<string, unknown> = {};
  const pruned = pruneAgentReasoningEffortBySlot(draft.reasoningEffortBySlot, draft.llmBindings, models);
  metadata.llmReasoningEffort = pruned;
  return metadata;
}
