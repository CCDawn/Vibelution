import { describe, expect, it } from "vitest";

import {
  applyResearchEdgeTemplateToEdge,
  applyResearchModuleTemplateToNode,
  canvasViewportFromView,
  clampCanvasZoom,
  createCustomResearchEdgeTemplate,
  createCustomResearchModuleTemplate,
  createResearchNodeFromTemplate,
  deleteCanvasSelection,
  findResearchModuleTemplate,
  findResearchEdgeTemplate,
  isValidEdgeReconnectTarget,
  isValidResearchFlowConnection,
  normalizeEdgeCondition,
  pushCanvasHistory,
  readCustomResearchTemplates,
  researchFlowExecutionBlockReason,
  readableResearchFlowIssueMessage,
  researchFlowIssueAdvice,
  researchFlowLockBlockReason,
  sameCanvasSelection,
  researchFlowNodeContract,
  researchFlowEdgeTemplateKey,
  researchFlowModuleTemplateKey,
  RESEARCH_MODULE_TEMPLATES,
  validateResearchFlowCanvasContract,
  stepCanvasHistory,
  summarizeDeleteImpact,
  shouldBlockCanvasLeave,
  nextTemplateNodeId,
  writeCustomResearchTemplates,
} from "./ResearchFlowCanvasRoute";

function memoryStorage() {
  const values = new Map<string, string>();
  return {
    getItem: (key: string) => values.get(key) ?? null,
    setItem: (key: string, value: string) => {
      values.set(key, value);
    },
  };
}

const baseCanvas = {
  schemaVersion: 1,
  updatedAt: "2026-05-26T00:00:00Z",
  path: "workspace/prompts/research/flow_canvas.json",
  viewport: { x: 0, y: 0, zoom: 1 },
  nodes: [
    {
      id: "broad_search",
      label: "广搜",
      type: "agent",
      status: "idle",
      x: 10,
      y: 10,
      agentKey: "",
      promptKey: "",
      llmConfigId: "",
      description: "",
      routeCondition: "",
    },
    {
      id: "deep_search",
      label: "深搜",
      type: "agent",
      status: "idle",
      x: 300,
      y: 10,
      agentKey: "",
      promptKey: "",
      llmConfigId: "",
      description: "",
      routeCondition: "",
    },
  ],
  edges: [
    {
      id: "edge_1",
      source: "broad_search",
      target: "deep_search",
      label: "进入深搜",
      condition: "completed",
      type: "success",
    },
  ],
};

describe("ResearchFlowCanvasRoute canvas rules", () => {
  it("clamps and persists viewport from the local view state", () => {
    expect(clampCanvasZoom(0.1)).toBe(0.5);
    expect(clampCanvasZoom(2.4)).toBe(1.8);
    expect(canvasViewportFromView({ x: 12.4, y: -18.6 }, 1.234)).toEqual({
      x: 12,
      y: -19,
      zoom: 1.23,
    });
  });

  it("prevents reconnecting an edge endpoint into a self loop", () => {
    const edge = { source: "broad_search", target: "deep_search" };

    expect(isValidEdgeReconnectTarget(edge, "source", "review_gate")).toBe(true);
    expect(isValidEdgeReconnectTarget(edge, "target", "review_gate")).toBe(true);
    expect(isValidEdgeReconnectTarget(edge, "source", "deep_search")).toBe(false);
    expect(isValidEdgeReconnectTarget(edge, "target", "broad_search")).toBe(false);
    expect(isValidEdgeReconnectTarget(edge, "target", "")).toBe(false);
  });

  it("keeps edge conditions inside the enumerated route condition set", () => {
    expect(normalizeEdgeCondition("approved")).toBe("approved");
    expect(normalizeEdgeCondition(" NEEDS_EVIDENCE ")).toBe("needs_evidence");
    expect(normalizeEdgeCondition("人工手填条件")).toBe("completed");
  });

  it("creates canvas nodes from reusable research module templates", () => {
    expect(RESEARCH_MODULE_TEMPLATES.map((template) => template.key)).toEqual(
      expect.arrayContaining([
        "knowledge_lookup",
        "literature_project_parse",
        "semantic_cluster",
        "novelty_reverse_check",
        "evidence_review",
      ]),
    );

    const template = findResearchModuleTemplate("literature_project_parse");
    const firstNode = createResearchNodeFromTemplate(template, baseCanvas.nodes, { x: 42, y: 84 });
    expect(firstNode).toMatchObject({
      id: "literature_project_parse",
      label: "文献/项目解析",
      type: "tool",
      agentKey: "literature_project_parse",
      promptKey: "",
      llmConfigId: "",
      x: 42,
      y: 84,
    });

    const duplicateNode = createResearchNodeFromTemplate(template, [...baseCanvas.nodes, firstNode]);
    expect(duplicateNode.id).toBe("literature_project_parse_2");
    expect(duplicateNode.label).toBe("文献/项目解析 2");
    expect(nextTemplateNodeId([...baseCanvas.nodes, firstNode], "literature_project_parse")).toBe("literature_project_parse_2");
    expect(findResearchModuleTemplate("missing_template").key).toBe("knowledge_lookup");
  });

  it("applies module and edge templates as reusable presets", () => {
    const moduleTemplate = findResearchModuleTemplate("literature_project_parse");
    const createdNode = createResearchNodeFromTemplate(moduleTemplate, baseCanvas.nodes, { x: 42, y: 84 });
    expect(researchFlowModuleTemplateKey(createdNode)).toBe("literature_project_parse");
    expect(applyResearchModuleTemplateToNode(moduleTemplate)).toMatchObject({
      label: "文献/项目解析",
      type: "tool",
      agentKey: "literature_project_parse",
      promptKey: "",
      llmConfigId: "",
    });

    const edgeTemplate = findResearchEdgeTemplate("evidence_backtrack");
    expect(edgeTemplate.label).toBe("证据回路");
    expect(applyResearchEdgeTemplateToEdge(edgeTemplate)).toMatchObject({
      label: "缺口补搜",
      type: "evidence_loop",
      condition: "needs_evidence",
    });
    expect(researchFlowEdgeTemplateKey({ type: "evidence_loop", condition: "needs_evidence" })).toBe("evidence_backtrack");
    expect(researchFlowEdgeTemplateKey({ type: "success", condition: "completed" })).toBe("main_flow");

    const customNode = {
      ...createdNode,
      label: "自定义解析",
      routeCondition: "解析后进入自定义聚类。",
    };
    const customModuleTemplate = createCustomResearchModuleTemplate(customNode, RESEARCH_MODULE_TEMPLATES);
    expect(customModuleTemplate).toMatchObject({
      group: "自定义模板",
      label: "自定义解析",
      status: "idle",
    });
    expect(researchFlowModuleTemplateKey(customNode, [...RESEARCH_MODULE_TEMPLATES, customModuleTemplate])).toBe(customModuleTemplate.key);

    const customEdgeTemplate = createCustomResearchEdgeTemplate(
      { ...baseCanvas.edges[0], label: "自定义继续" },
      "广搜",
      "深搜",
      [edgeTemplate],
    );
    expect(customEdgeTemplate).toMatchObject({
      group: "自定义模板",
      label: "自定义继续",
      edgeLabel: "自定义继续",
      condition: "completed",
      type: "success",
    });
    expect(
      researchFlowEdgeTemplateKey(
        { type: customEdgeTemplate.type, condition: customEdgeTemplate.condition, label: customEdgeTemplate.edgeLabel },
        [edgeTemplate, customEdgeTemplate],
      ),
    ).toBe(customEdgeTemplate.key);

    const storage = memoryStorage();
    expect(writeCustomResearchTemplates({ moduleTemplates: [customModuleTemplate], edgeTemplates: [customEdgeTemplate] }, storage)).toBe(true);
    expect(readCustomResearchTemplates(storage)).toMatchObject({
      moduleTemplates: [{ key: customModuleTemplate.key, label: "自定义解析", group: "自定义模板" }],
      edgeTemplates: [{ key: customEdgeTemplate.key, label: "自定义继续", group: "自定义模板" }],
    });
  });

  it("validates research flow contracts before save and execution", () => {
    const validCanvas = {
      ...baseCanvas,
      nodes: [
        ...baseCanvas.nodes,
        {
          id: "semantic_cluster",
          label: "聚类",
          type: "tool",
          status: "idle",
          x: 620,
          y: 10,
          agentKey: "semantic_cluster",
          promptKey: "",
          llmConfigId: "",
          description: "",
          routeCondition: "",
        },
      ],
      edges: [
        ...baseCanvas.edges,
      ],
    };
    expect(validateResearchFlowCanvasContract(validCanvas).valid).toBe(true);
    expect(researchFlowNodeContract(baseCanvas.nodes[0])?.outputs.completed).toContain("sources");
    expect(isValidResearchFlowConnection(validCanvas, "broad_search", "deep_search", "completed")).toBe(true);
    expect(isValidResearchFlowConnection(validCanvas, "broad_search", "semantic_cluster", "completed")).toBe(false);

    const badCondition = {
      ...validCanvas,
      edges: [
        {
          id: "edge_drift",
          source: "broad_search",
          target: "deep_search",
          label: "错误箭头",
          condition: "needs_evidence",
          type: "success",
        },
      ],
    };
    const badValidation = validateResearchFlowCanvasContract(badCondition);
    expect(badValidation.valid).toBe(false);
    expect(badValidation.summary.errorCount).toBeGreaterThan(0);
  });

  it("renders validation issues as user-facing diagnosis text", () => {
    expect(
      readableResearchFlowIssueMessage({
        message: "模块 broad_search 缺少分支路由：needs_evidence。",
      }),
    ).toBe("模块 broad_search 缺少分支路由：证据不足。");
    expect(researchFlowIssueAdvice({ code: "node_missing_outcome_route", severity: "warning" })).toBe(
      "为该模块补一条匹配缺失结果的路由，或调整模块输出契约。",
    );
    expect(researchFlowIssueAdvice({ code: "unknown_error", severity: "error" })).toBe(
      "先修复此项，否则画布不能保存和执行。",
    );
  });

  it("tracks undo and redo snapshots while clearing redo after a new edit", () => {
    const firstEdit = {
      ...baseCanvas,
      nodes: baseCanvas.nodes.map((node) => (node.id === "broad_search" ? { ...node, label: "广搜 A" } : node)),
    };
    const secondEdit = {
      ...firstEdit,
      nodes: firstEdit.nodes.map((node) => (node.id === "deep_search" ? { ...node, label: "深搜 B" } : node)),
    };

    const history = pushCanvasHistory({ past: [], future: [] }, baseCanvas);
    const undo = stepCanvasHistory(history, firstEdit, "undo");

    expect(undo?.canvas.nodes[0].label).toBe("广搜");
    expect(undo?.history.future[0].nodes[0].label).toBe("广搜 A");

    const redo = undo && stepCanvasHistory(undo.history, undo.canvas, "redo");
    expect(redo?.canvas.nodes[0].label).toBe("广搜 A");

    const diverged = pushCanvasHistory(undo?.history ?? { past: [], future: [] }, secondEdit);
    expect(diverged.future).toHaveLength(0);
  });

  it("summarizes delete impact before destructive canvas edits", () => {
    expect(summarizeDeleteImpact(baseCanvas, { kind: "node", id: "broad_search" })).toMatchObject({
      canDelete: true,
      subject: "模块「广搜」",
      connectedEdgeCount: 1,
    });
    expect(summarizeDeleteImpact(baseCanvas, { kind: "edge", id: "edge_1" })).toMatchObject({
      canDelete: true,
      subject: "路由「进入深搜」",
      connectedEdgeCount: 0,
    });
    expect(summarizeDeleteImpact({ ...baseCanvas, nodes: [baseCanvas.nodes[0]], edges: [] }, { kind: "node", id: "broad_search" })).toMatchObject({
      canDelete: false,
      detail: "至少保留一个模块，不能把画布删空。",
    });
    expect(summarizeDeleteImpact(baseCanvas, null)).toMatchObject({ canDelete: false });
  });

  it("deletes a selected node and its connected edges from the canvas draft", () => {
    const updated = deleteCanvasSelection(baseCanvas, { kind: "node", id: "broad_search" });

    expect(updated.nodes.map((node) => node.id)).toEqual(["deep_search"]);
    expect(updated.edges).toEqual([]);
  });

  it("matches delete confirmation only for the same selected canvas item", () => {
    expect(sameCanvasSelection({ kind: "node", id: "a" }, { kind: "node", id: "a" })).toBe(true);
    expect(sameCanvasSelection({ kind: "node", id: "a" }, { kind: "edge", id: "a" })).toBe(false);
    expect(sameCanvasSelection(null, { kind: "node", id: "a" })).toBe(false);
  });

  it("blocks route changes only while the canvas has unsaved or saving work", () => {
    expect(
      shouldBlockCanvasLeave({
        dirty: true,
        saving: false,
        currentPathname: "/research/flow-canvas",
        nextPathname: "/research",
      }),
    ).toBe(true);
    expect(
      shouldBlockCanvasLeave({
        dirty: false,
        saving: true,
        currentPathname: "/research/flow-canvas",
        nextPathname: "/research",
      }),
    ).toBe(true);
    expect(
      shouldBlockCanvasLeave({
        dirty: true,
        saving: false,
        currentPathname: "/research/flow-canvas",
        nextPathname: "/research/flow-canvas",
      }),
    ).toBe(false);
    expect(
      shouldBlockCanvasLeave({
        dirty: false,
        saving: false,
        currentPathname: "/research/flow-canvas",
        nextPathname: "/research",
      }),
    ).toBe(false);
  });

  it("explains why flow execution is blocked", () => {
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "",
        sessionLoading: true,
        canvasLocked: true,
        dirty: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("科研会话正在加载，加载完成后即可执行。");
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "",
        sessionLoading: false,
        canvasLocked: true,
        dirty: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("先选择一个科研会话后再执行。");
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "research-session-1",
        sessionLoading: false,
        canvasLocked: true,
        dirty: true,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("画布有未保存修改，先保存后再执行。");
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "research-session-1",
        sessionLoading: false,
        canvasLocked: true,
        dirty: false,
        executing: false,
        validationErrorCount: 1,
      }),
    ).toBe("当前画布存在契约错误，先修复输入输出和路由规则。");
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "research-session-1",
        sessionLoading: false,
        canvasLocked: false,
        dirty: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("先锁定画布进入观察模式，再执行科研流程。");
    expect(
      researchFlowExecutionBlockReason({
        sessionId: "research-session-1",
        sessionLoading: false,
        canvasLocked: true,
        dirty: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("");
  });

  it("requires a clean locked canvas before execution can start", () => {
    expect(
      researchFlowLockBlockReason({
        draftReady: false,
        dirty: false,
        saving: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("画布加载完成后才能锁定观察。");
    expect(
      researchFlowLockBlockReason({
        draftReady: true,
        dirty: true,
        saving: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("画布有未保存修改，先保存后再锁定。");
    expect(
      researchFlowLockBlockReason({
        draftReady: true,
        dirty: false,
        saving: false,
        executing: true,
        validationErrorCount: 0,
      }),
    ).toBe("节点执行中，完成后才能解除锁定。");
    expect(
      researchFlowLockBlockReason({
        draftReady: true,
        dirty: false,
        saving: false,
        executing: false,
        validationErrorCount: 1,
      }),
    ).toBe("当前画布存在契约错误，先修复后再锁定。");
    expect(
      researchFlowLockBlockReason({
        draftReady: true,
        dirty: false,
        saving: false,
        executing: false,
        validationErrorCount: 0,
      }),
    ).toBe("");
  });
});
