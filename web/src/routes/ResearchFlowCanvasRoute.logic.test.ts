import { describe, expect, it } from "vitest";

import {
  applyResearchAgentBindingToNode,
  applyResearchEdgeTemplateToEdge,
  applyResearchModuleTemplateToNode,
  canvasViewportFromView,
  clampCanvasZoom,
  createCustomResearchEdgeTemplate,
  createCustomResearchModuleTemplate,
  createResearchNodeFromTemplate,
  deleteCanvasSelection,
  findResearchEdgeTemplate,
  findResearchModuleTemplate,
  isValidEdgeReconnectTarget,
  isValidResearchFlowConnection,
  nextTemplateNodeId,
  normalizeEdgeCondition,
  normalizeResearchFlowNodesForSave,
  pushCanvasHistory,
  readCustomResearchTemplates,
  readableResearchFlowIssueMessage,
  researchFlowEdgeTemplateKey,
  researchFlowExecutionBlockReason,
  researchFlowIssueAdvice,
  researchFlowLockBlockReason,
  researchFlowModuleTemplateKey,
  researchFlowUnlockBlockReason,
  RESEARCH_EDGE_TEMPLATES,
  RESEARCH_MODULE_TEMPLATES,
  sameCanvasSelection,
  shouldBlockCanvasLeave,
  stepCanvasHistory,
  summarizeDeleteImpact,
  validateResearchFlowCanvasContract,
  writeCustomResearchTemplates,
} from "./ResearchFlowCanvasRoute";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => values.set(key, value),
  };
}

const baseCanvas = {
  schemaVersion: 1,
  canvasKind: "research_flow_canvas",
  updatedAt: "2026-05-26T00:00:00Z",
  path: "workspace/prompts/research/flow_canvas.json",
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [
    {
      id: "broad_search",
      label: "广撒网探索",
      type: "agent",
      status: "ready",
      x: 80,
      y: 80,
      agentId: "agent-research-broad",
      agentKey: "broad",
      promptKey: "broad",
      llmConfigId: "",
      description: "从开放目标出发发现候选方向。",
      routeCondition: "输入开放目标后启动。",
    },
    {
      id: "deep_search",
      label: "定向深搜",
      type: "agent",
      status: "idle",
      x: 360,
      y: 80,
      agentId: "agent-research-deep",
      agentKey: "deep",
      promptKey: "deep",
      llmConfigId: "",
      description: "围绕候选方向补充证据。",
      routeCondition: "广搜完成后继续。",
    },
  ],
  edges: [
    {
      id: "edge_broad_deep",
      source: "broad_search",
      target: "deep_search",
      label: "完成后继续",
      condition: "completed",
      type: "success",
    },
  ],
};

describe("ResearchFlowCanvasRoute flow canvas rules", () => {
  it("keeps canvas viewport and reconnect helpers deterministic", () => {
    expect(clampCanvasZoom(0.1)).toBe(0.5);
    expect(clampCanvasZoom(2.4)).toBe(1.8);
    expect(canvasViewportFromView({ x: 12.4, y: -18.6 }, 1.234)).toEqual({ x: 12, y: -19, zoom: 1.23 });

    const edge = { source: "broad_search", target: "deep_search" };
    expect(isValidEdgeReconnectTarget(edge, "source", "research_agent")).toBe(true);
    expect(isValidEdgeReconnectTarget(edge, "target", "broad_search")).toBe(false);
  });

  it("defaults unknown route conditions back to the flow success condition", () => {
    expect(normalizeEdgeCondition("completed")).toBe("completed");
    expect(normalizeEdgeCondition(" NEEDS_EVIDENCE ")).toBe("needs_evidence");
    expect(normalizeEdgeCondition("人工手填条件")).toBe("completed");
  });

  it("creates and matches reusable module and route templates", () => {
    expect(RESEARCH_MODULE_TEMPLATES.map((template) => template.key)).toEqual(
      expect.arrayContaining(["broad_search", "deep_search", "evidence_review", "theme_generation", "theme_card"]),
    );
    expect(RESEARCH_MODULE_TEMPLATES.every((template) => template.type === "agent")).toBe(true);
    expect(RESEARCH_MODULE_TEMPLATES.map((template) => template.key)).not.toEqual(
      expect.arrayContaining(["knowledge_lookup", "literature_project_parse", "semantic_cluster", "novelty_reverse_check", "human_choice"]),
    );
    expect(RESEARCH_MODULE_TEMPLATES.map((template) => template.key)).not.toContain("research_ceo_agent");
    expect(RESEARCH_MODULE_TEMPLATES.some((template) => "llmConfigId" in template)).toBe(false);
    expect(RESEARCH_EDGE_TEMPLATES.map((template) => template.key)).toEqual(
      expect.arrayContaining(["main_flow", "evidence_backtrack", "approval_gate", "human_handoff", "selection"]),
    );
    expect(RESEARCH_EDGE_TEMPLATES.map((template) => template.key)).not.toContain("collaboration_chat");

    const template = findResearchModuleTemplate("broad_search");
    const firstNode = createResearchNodeFromTemplate(template, baseCanvas.nodes, { x: 42, y: 84 });
    expect(firstNode).toMatchObject({
      id: "broad_search_2",
      label: "广撒网 agent 2",
      type: "agent",
      agentKey: "broad",
      promptKey: "broad",
      llmConfigId: "",
      x: 42,
      y: 84,
    });
    expect(nextTemplateNodeId([...baseCanvas.nodes, firstNode], "broad_search")).toBe("broad_search_3");
    expect(findResearchModuleTemplate("missing_template").key).toBe("broad_search");
    expect(researchFlowModuleTemplateKey(createResearchNodeFromTemplate(findResearchModuleTemplate("deep_search"), baseCanvas.nodes))).toBe("deep_search");
    expect(applyResearchModuleTemplateToNode(findResearchModuleTemplate("deep_search"))).toMatchObject({
      label: "定向深搜 agent",
      type: "agent",
      agentKey: "deep",
      promptKey: "deep",
      llmConfigId: "",
    });

    const edgeTemplate = findResearchEdgeTemplate("main_flow");
    expect(applyResearchEdgeTemplateToEdge(edgeTemplate)).toMatchObject({
      label: "完成后继续",
      type: "success",
      condition: "completed",
    });
    expect(researchFlowEdgeTemplateKey({ type: "success", condition: "completed" })).toBe("main_flow");
  });

  it("persists custom templates through storage", () => {
    const customNode = {
      ...createResearchNodeFromTemplate(findResearchModuleTemplate("deep_search"), baseCanvas.nodes),
      label: "自定义深搜 agent",
      llmConfigId: "stale_legacy_profile",
      routeCondition: "复用上一轮候选线索后继续。",
    };
    const customModuleTemplate = createCustomResearchModuleTemplate(customNode, RESEARCH_MODULE_TEMPLATES);
    expect("llmConfigId" in customModuleTemplate).toBe(false);
    const customEdgeTemplate = createCustomResearchEdgeTemplate(
      { ...baseCanvas.edges[0], label: "复核后继续", condition: "approved", type: "approval_gate" },
      "证据审查",
      "主题生成",
      [findResearchEdgeTemplate("approval_gate")],
    );

    const storage = memoryStorage();
    expect(writeCustomResearchTemplates({ moduleTemplates: [customModuleTemplate], edgeTemplates: [customEdgeTemplate] }, storage)).toBe(true);
    expect(readCustomResearchTemplates(storage)).toMatchObject({
      moduleTemplates: [{ key: customModuleTemplate.key, label: "自定义深搜 agent", group: "自定义模板" }],
      edgeTemplates: [{ key: customEdgeTemplate.key, label: "复核后继续", group: "自定义模板" }],
    });
    expect(readCustomResearchTemplates(storage).moduleTemplates.some((template) => "llmConfigId" in template)).toBe(false);
  });

  it("saves flow nodes with agentId as the primary binding", () => {
    const agent = {
      key: "broad",
      label: "广撒网 Agent",
      promptFilename: "broad.md",
      templateId: "broad",
      llmConfigId: "research_broad_profile",
      enabled: true,
      agentId: "agent-research-broad",
    };

    expect(applyResearchAgentBindingToNode(agent)).toEqual({
      agentId: "agent-research-broad",
      agentKey: "broad",
      promptKey: "broad",
      llmConfigId: "",
    });
    expect(normalizeResearchFlowNodesForSave([{ ...baseCanvas.nodes[0], llmConfigId: "stale_legacy_profile" }], [agent])[0]).toMatchObject({
      agentId: "agent-research-broad",
      agentKey: "broad",
      promptKey: "broad",
      llmConfigId: "",
    });
  });

  it("validates flow canvas structure before save", () => {
    expect(validateResearchFlowCanvasContract(baseCanvas).valid).toBe(true);
    expect(isValidResearchFlowConnection(baseCanvas, "deep_search", "broad_search", "completed", "", "success")).toBe(false);
    expect(isValidResearchFlowConnection(baseCanvas, "broad_search", "broad_search", "completed")).toBe(false);

    const unsupportedValidation = validateResearchFlowCanvasContract({
      ...baseCanvas,
      nodes: [...baseCanvas.nodes, { ...baseCanvas.nodes[0], id: "unknown_node", label: "未知节点", type: "unknown" }],
    });
    expect(unsupportedValidation.valid).toBe(false);
    expect(unsupportedValidation.issues.map((issue) => issue.code)).toContain("node_type_not_supported");

    const badValidation = validateResearchFlowCanvasContract({
      ...baseCanvas,
      edges: [{ id: "edge_drift", source: "broad_search", target: "deep_search", label: "错误箭头", condition: "needs_evidence", type: "success" }],
    });
    expect(badValidation.valid).toBe(false);
    expect(badValidation.issues.map((issue) => issue.code)).toContain("edge_type_condition_mismatch");
  });

  it("renders flow issues as user-facing diagnosis text", () => {
    expect(readableResearchFlowIssueMessage({ message: "路由 edge_1 的触发条件 needs_evidence 与箭头类型 success 不一致。" })).toBe(
      "路由 edge_1 的触发条件 证据不足 与箭头类型 success 不一致。",
    );
    expect(researchFlowIssueAdvice({ code: "edge_condition_not_produced", severity: "error" })).toBe("检查起点输出、终点输入和触发条件是否匹配。");
    expect(researchFlowIssueAdvice({ code: "unknown_error", severity: "error" })).toBe("先修复此项，否则画布不能保存和执行。");
  });

  it("tracks undo and redo snapshots while clearing redo after a new edit", () => {
    const firstEdit = { ...baseCanvas, nodes: baseCanvas.nodes.map((node) => (node.id === "broad_search" ? { ...node, label: "广撒网探索 A" } : node)) };
    const secondEdit = {
      ...firstEdit,
      nodes: firstEdit.nodes.map((node) => (node.id === "deep_search" ? { ...node, label: "定向深搜 B" } : node)),
    };

    const history = pushCanvasHistory({ past: [], future: [] }, baseCanvas);
    const undo = stepCanvasHistory(history, firstEdit, "undo");
    expect(undo?.canvas.nodes[0].label).toBe("广撒网探索");
    expect(undo?.history.future[0].nodes[0].label).toBe("广撒网探索 A");
    const redo = undo && stepCanvasHistory(undo.history, undo.canvas, "redo");
    expect(redo?.canvas.nodes[0].label).toBe("广撒网探索 A");
    expect(pushCanvasHistory(undo?.history ?? { past: [], future: [] }, secondEdit).future).toHaveLength(0);
  });

  it("summarizes and applies destructive flow canvas edits", () => {
    expect(summarizeDeleteImpact(baseCanvas, { kind: "node", id: "broad_search" })).toMatchObject({
      canDelete: true,
      subject: "模块「广撒网探索」",
      connectedEdgeCount: 1,
    });
    expect(summarizeDeleteImpact(baseCanvas, { kind: "edge", id: "edge_broad_deep" })).toMatchObject({
      canDelete: true,
      subject: "路由「完成后继续」",
      connectedEdgeCount: 0,
    });
    expect(summarizeDeleteImpact({ ...baseCanvas, nodes: [baseCanvas.nodes[0]], edges: [] }, { kind: "node", id: "broad_search" })).toMatchObject({
      canDelete: false,
      detail: "至少保留一个模块，不能把画布删空。",
    });
    expect(deleteCanvasSelection(baseCanvas, { kind: "node", id: "broad_search" }).nodes.map((node) => node.id)).toEqual(["deep_search"]);
    expect(deleteCanvasSelection(baseCanvas, { kind: "node", id: "broad_search" }).edges).toEqual([]);
    expect(sameCanvasSelection({ kind: "node", id: "a" }, { kind: "node", id: "a" })).toBe(true);
    expect(sameCanvasSelection({ kind: "node", id: "a" }, { kind: "edge", id: "a" })).toBe(false);
  });

  it("blocks route changes only while the canvas has unsaved or saving work", () => {
    expect(shouldBlockCanvasLeave({ dirty: true, saving: false, currentPathname: "/research/flow-canvas", nextPathname: "/research" })).toBe(true);
    expect(shouldBlockCanvasLeave({ dirty: false, saving: true, currentPathname: "/research/flow-canvas", nextPathname: "/research" })).toBe(true);
    expect(shouldBlockCanvasLeave({ dirty: true, saving: false, currentPathname: "/research/flow-canvas", nextPathname: "/research/flow-canvas" })).toBe(false);
  });

  it("explains why the flow canvas is not ready for locked execution", () => {
    expect(researchFlowExecutionBlockReason({ canvasLocked: true, dirty: true, validationErrorCount: 0 })).toBe("画布有未保存修改，先保存后再执行。");
    expect(researchFlowExecutionBlockReason({ canvasLocked: true, dirty: false, validationErrorCount: 1 })).toBe("当前画布存在契约错误，先修复输入输出和路由规则。");
    expect(researchFlowExecutionBlockReason({ canvasLocked: false, dirty: false, validationErrorCount: 0 })).toBe(
      "先锁定画布进入观察模式，再执行科研流程。",
    );
    expect(researchFlowExecutionBlockReason({ canvasLocked: true, dirty: false, validationErrorCount: 0 })).toBe("");
  });

  it("requires a clean locked canvas before observation can start", () => {
    expect(researchFlowLockBlockReason({ draftReady: false, dirty: false, saving: false, executing: false, validationErrorCount: 0 })).toBe("画布加载完成后才能锁定观察。");
    expect(researchFlowLockBlockReason({ draftReady: true, dirty: true, saving: false, executing: false, validationErrorCount: 0 })).toBe("画布有未保存修改，先保存后再锁定。");
    expect(researchFlowLockBlockReason({ draftReady: true, dirty: false, saving: false, executing: true, validationErrorCount: 0 })).toBe("节点执行中，完成后才能锁定观察。");
    expect(researchFlowLockBlockReason({ draftReady: true, dirty: false, saving: false, executing: false, validationErrorCount: 1 })).toBe("当前画布存在契约错误，先修复后再锁定。");
    expect(researchFlowUnlockBlockReason({ saving: false, executing: false })).toBe("");
    expect(researchFlowUnlockBlockReason({ saving: false, executing: true })).toBe("节点执行中，完成后才能取消锁定。");
    expect(researchFlowUnlockBlockReason({ saving: true, executing: false })).toBe("画布正在保存，保存完成后才能取消锁定。");
  });
});
