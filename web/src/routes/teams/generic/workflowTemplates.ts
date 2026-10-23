import type { Flow, WorkflowMember } from "./workflowModel";

const EXAMPLE_FLOWS: Omit<Flow, "revision" | "updatedAt">[] = [
  {
    id: "analysis", name: "资料调研与交叉验证", description: "整理资料、交叉核验，确认后形成交付文档。",
    fields: [
      { id: "goal", label: "任务说明", kind: "paragraph", required: true, options: [] },
      { id: "scope", label: "资料范围", kind: "select", required: true, options: ["公开资料", "已有文档", "公开资料与已有文档"] },
    ],
    steps: [
      { id: "input", label: "接收任务", kind: "input", owner: "用户", instruction: "收集任务说明和资料范围。入口字段由流程作者配置。" },
      { id: "collect", label: "整理资料", kind: "agent", owner: "analyst", instruction: "围绕本次输入整理相关资料，保留来源与关键论据。" },
      { id: "review", label: "交叉核验", kind: "agent", owner: "reviewer", instruction: "检查来源、事实和结论，标记有分歧或证据不足的内容。" },
      { id: "confirm", label: "确认结果", kind: "human", owner: "用户", instruction: "阅读初稿，确认范围和结论；需要补充时退回上一节点。" },
      { id: "deliver", label: "生成交付文档", kind: "output", owner: "writer", instruction: "根据已确认内容生成结构清楚、包含来源的交付文档。" },
    ],
  },
  {
    id: "document", name: "文档审查", description: "按自定义审查重点检查文档，确认修改建议。",
    fields: [
      { id: "document", label: "文档内容", kind: "paragraph", required: true, options: [] },
      { id: "focus", label: "审查重点", kind: "select", required: true, options: ["逻辑与事实", "表达与结构", "格式与规范"] },
      { id: "audience", label: "目标读者", kind: "text", required: false, options: [] },
    ],
    steps: [
      { id: "input", label: "接收文档", kind: "input", owner: "用户", instruction: "收集文档和本次审查重点。" },
      { id: "read", label: "分析文档", kind: "agent", owner: "analyst", instruction: "识别文档结构，逐项分析需要改进的内容。" },
      { id: "check", label: "复核建议", kind: "agent", owner: "reviewer", instruction: "核对每条建议是否有原文依据，避免改变原意。" },
      { id: "confirm", label: "确认修改建议", kind: "human", owner: "用户", instruction: "选择接受修改建议，或补充要求后重新审查。" },
      { id: "deliver", label: "交付审查结果", kind: "output", owner: "writer", instruction: "汇总已确认的审查意见。" },
    ],
  },
];


export function createWorkflow(name: string, template: string, members: WorkflowMember[]): Flow {
  const base = EXAMPLE_FLOWS.find(flow => flow.id === template);
  const ids = members.filter(member => member.available).map(member => member.id);
  const ownerMap: Record<string, string> = { analyst: ids[0] || "", reviewer: ids[1] || ids[0] || "", writer: ids[2] || ids[0] || "" };
  const flow: Flow = base ? { ...structuredClone(base), revision: 0, updatedAt: "" } : {
    id: "", name: "", description: "", fields: [], revision: 0, updatedAt: "",
    steps: [
      { id: "input", label: "接收输入", kind: "input", owner: "用户", instruction: "" },
      { id: "deliver", label: "交付结果", kind: "output", owner: ids[0] || "", instruction: "" },
    ],
  };
  flow.id = `flow-${crypto.randomUUID()}`;
  flow.name = name.trim();
  flow.steps = flow.steps.map(step => ({ ...step, owner: ownerMap[step.owner] ?? step.owner }));
  return flow;
}
export const workflowTemplateOptions = [{ id: "blank", label: "空白流程" }, ...EXAMPLE_FLOWS.map(flow => ({ id: flow.id, label: `${flow.name}模板` }))];

export const workflowTemplatePreviews = EXAMPLE_FLOWS.map(flow => ({
  id: flow.id, name: flow.name, description: flow.description,
  stepCount: flow.steps.length, stepLabels: flow.steps.map(step => step.label),
}));
