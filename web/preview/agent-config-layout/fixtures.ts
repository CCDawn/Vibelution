import type { AgentPersonaDraft } from "../../src/routes/AgentPersonaProfilePanel";
import type { AgentTaskDraft } from "../../src/routes/AgentTaskProfilePanel";

// Field names mirror the existing panels. Values are safe fixtures, never live config.
export const initial = {
  basic: {
    displayName: "研究助手", status: "active", permissionPreset: "request_approval",
    dialogue: "OpenAI / GPT-5.4", reasoningEffort: "默认", promptTemplateId: "研究任务 · 通用模板",
    toolPolicyId: "研究工具策略", memoryPolicyId: "研究助手私有记忆",
    mentalModel: "沿用对话模型", summary: "沿用对话模型", subagentPlanning: "沿用对话模型", subagentExecution: "沿用对话模型", vision: "沿用对话模型",
    mode: "全局配置快照", enabled: true, maxTokenLimit: "120000", maxCompressionsPerSession: "0",
    lightThreshold: "60", standardThreshold: "75", deepThreshold: "85", emergencyThreshold: "95",
    lightSummaryChars: "6000", standardSummaryChars: "4000", deepSummaryChars: "2500", emergencySummaryChars: "1200",
    keepAiMessages: "4", preserveErrors: true, extractKeyDecisions: true,
  },
  persona: {
    gender: "", age: "", pronouns: "", expertise: "文献分析, 证据核对",
    personality: "谨慎，重视证据，明确表达不确定性。", communicationStyle: "先给结论，再说明依据；避免重复解释。",
    background: "", collaborationPreference: "有分歧时先说明影响和建议。", identityNotes: "",
  } satisfies AgentPersonaDraft,
  task: {
    mission: "协助完成有证据支持的研究分析。", taskTypes: "文献分析, 方案比较",
    responsibilities: "收集资料，核对来源，比较方案，并给出可验证的下一步。",
    preferredTasks: "", avoidTasks: "", successCriteria: "结论可追溯到来源，未知项明确标注。",
    deliverables: "研究摘要、对比表与来源链接。", constraints: "不把推测写成事实。", handoffNotes: "",
  } satisfies AgentTaskDraft,
  memory: { enabled: true, readSharedGroups: [], writeSharedGroups: [], readKnowledgeBaseIds: ["research-example"], proposeKnowledgeBaseIds: [], reviewKnowledgeBaseIds: [], rateKnowledgeBaseIds: [] },
  governance: { allowSubagents: false, allowWakeMessages: false, maxConcurrent: "2", maxDepth: "1", allowedContextModes: ["isolated"], supervisionEnabled: false, requiresReview: false, reviewMode: "建议", evidenceLevel: "标准" },
};
export type SaveGroup = keyof typeof initial;
export type Draft = Record<string, string | boolean | string[]>;
export type Bundle = Record<SaveGroup, Draft>;
export const groupLabels: Record<SaveGroup, string> = { basic: "基本配置", persona: "人物档案", task: "任务档案", memory: "记忆策略", governance: "委派与监督" };
export function createBundle(id: string): Bundle {
  const result: Bundle = structuredClone(initial);
  if (id === "coding") {
    result.basic.displayName = "开发助手";
    result.basic.dialogue = "Anthropic / Claude Sonnet 4.6";
    result.basic.promptTemplateId = "软件开发 · 通用模板";
    result.basic.toolPolicyId = "开发工具策略";
    result.basic.memoryPolicyId = "开发助手私有记忆";
    result.persona.expertise = "软件开发, 代码审查";
    result.task.mission = "根据任务要求实现、验证并交付代码改动。";
  }
  return result;
}
