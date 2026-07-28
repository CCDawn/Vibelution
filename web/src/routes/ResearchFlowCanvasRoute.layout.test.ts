import { describe, expect, it } from "vitest";

import styles from "./ResearchFlowCanvasRoute.styles";
import routeSource from "./ResearchFlowCanvasRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";

function expectLightRepeatedSurface(style: string) {
  expect(style).not.toContain("bg-[var(--vui-surface-glass)]");
  expect(style).not.toContain("shadow-[var(--vui-shadow-hairline)]");
}

describe("ResearchFlowCanvasRoute layout contract", () => {
  it("routes Research flow canvas controls through VUI primitives", () => {
    expect(routeSource).toContain('from "../components/vui"');
    expect(routeSource).toContain("<VButton");
    expect(routeSource).toContain("<VNativeInput");
    expect(routeSource).toContain("<VNativeSelect");
    expect(routeSource).toContain("<VNativeTextarea");
    expect(routeSource).toContain("<VRouteLinkButton");
    expect(routeSource).not.toContain('import { Link } from "react-router-dom"');
    expect(routeSource).not.toMatch(/<button\b/);
    expect(routeSource).not.toMatch(/<input\b/);
    expect(routeSource).not.toMatch(/<select\b/);
    expect(routeSource).not.toMatch(/<textarea\b/);
  });

  it("exposes a locked project organization canvas backed by the research organization graph", () => {
    expect(routerSource).toContain("ResearchFlowCanvasRoute");
    expect(routerSource).toContain("research/flow-canvas");
    expect(routeSource).toContain("/api/research/flow-canvas");
    expect(routeSource).not.toContain("/api/research/flow-canvas/execute");
    expect(routeSource).toContain("/api/research/organization");
    expect(routeSource).toContain("/api/research/organization/messages");
    expect(routeSource).toContain("workspace/research/organization_graph.json");
    expect(routeSource).toContain("Project Organization Canvas");
    expect(routeSource).toContain("科研组织画布");
    expect(routeSource).toContain("持续锁定到项目组织架构");
    expect(routeSource).toContain("画布持续只读同步");
    expect(routeSource).toContain("流程线与组织通信线使用同一份项目组织数据");
    expect(routeSource).toContain("canvasEditable = false");
    expect(routeSource).toContain("research_flow_canvas");
    expect(routeSource).not.toContain("research_agent_organization");
    expect(routeSource).toContain("组织通信");
    expect(routeSource).toContain("科研组织通信");
    expect(routeSource).toContain("提案面板");
    expect(routeSource).toContain("审计流");
    expect(routeSource).toContain("仅用于科研组织上下文消息");
    expect(routeSource).toContain("通用项目总群、@Agent 和撤回仍在对话页处理");
    expect(routeSource).toContain("这里只确认科研组织提案");
    expect(routeSource).toContain("通用 Agent 配置和工具权限仍由 Agent 管理承接");
    expect(routeSource).toContain("成员/角色回团队页，工具权限回 Agent 管理");
    expect(routeSource).not.toContain("工具权限来自每个 Agent 的 ToolPolicy");
    expect(routeSource).toContain("inspectorView");
    expect(routeSource).toContain("同步检查");
    expect(routeSource).toContain("错误与警告");
    expect(routeSource).toContain("focusValidationIssue");
    expect(routeSource).not.toContain("activeExecutionSessionId");
    expect(routeSource).toContain("持续锁定");
    expect(routeSource).toContain("useState(true)");
    expect(routeSource).toContain("绑定团队");
    expect(routeSource).toContain("科研团队");
    expect(routeSource).toContain("刷新组织图");
    expect(routeSource).not.toContain("执行下一节点");
    expect(routeSource).not.toContain("执行选中节点");
    expect(routeSource).not.toContain("执行前检查");
    expect(routeSource).not.toContain("添加模块");
    expect(routeSource).not.toContain("保存画布");
    expect(routeSource).toContain("readableResearchFlowIssueMessage");
    expect(routeSource).toContain("researchFlowIssueAdvice");
    expect(routeSource).toContain("refetchInterval: canvasLocked ? 2000 : false");
  });

  it("renders only organization Agent nodes and communication edges in the main canvas", () => {
    expect(routeSource).toContain("agentDisplayInfo");
    expect(routeSource).toContain("agentDisplayForFlowNode");
    expect(routeSource).toContain("styles[agentRoleClass(display.tone)]");
    expect(routeSource).toContain("Agent ID");
    expect(routeSource).toContain("组织角色");
    expect(routeSource).toContain("职级");
    expect(routeSource).toContain("通信线 / 流程线");
    expect(routeSource).toContain("流程线与通讯线相同");
    expect(routeSource).not.toContain("addNode");
    expect(routeSource).not.toContain("deleteSelected");
    expect(routeSource).not.toContain("保存为模块模板");
    expect(routeSource).not.toContain("保存为线模板");
    expect(routeSource).not.toContain("useBlocker");
    expect(routeSource).not.toContain("WORKBENCH_EXIT_GUARD_EVENT");
    expect(routeSource).not.toContain("beforeunload");
    expect(routeSource).not.toContain("离开前要保存科研流程画布吗");
    expect(routeSource).toContain("handleNodePointerDown");
    expect(routeSource).toContain("connect.sourceId");
    expect(routeSource).toContain("nextEdgeId");
    expect(routeSource).toContain("RESEARCH_MODULE_TEMPLATES");
    expect(routeSource).toContain("createResearchNodeFromTemplate");
    expect(routeSource).toContain("nextTemplateNodeId");
    expect(routeSource).toContain("readCustomResearchTemplates");
    expect(routeSource).toContain("writeCustomResearchTemplates");
    expect(routeSource).toContain("createCustomResearchModuleTemplate");
    expect(routeSource).toContain("createCustomResearchEdgeTemplate");
    expect(routeSource).toContain("research_ceo_entry");
    expect(routeSource).toContain("organization_advisor_entry");
    expect(routeSource).toContain("broad_search");
    expect(routeSource).toContain("deep_search");
    expect(routeSource).toContain("evidence_review");
    expect(routeSource).toContain("theme_generation");
    expect(routeSource).toContain("theme_card");
    expect(routeSource).not.toContain("knowledge_lookup");
    expect(routeSource).not.toContain("literature_project_parse");
    expect(routeSource).not.toContain("semantic_cluster");
    expect(routeSource).not.toContain("novelty_reverse_check");
    expect(routeSource).not.toContain("human_choice");
    expect(routeSource).not.toContain("collaboration_chat");
    expect(routeSource).toContain("edgeGeometry");
    expect(routeSource).toContain("EDGE_TYPE_OPTIONS");
    expect(routeSource).toContain("EDGE_CONDITION_OPTIONS");
    expect(routeSource).toContain("normalizeEdgeCondition");
    expect(routeSource).toContain("edgeConditionLabel");
    expect(routeSource).toContain("edgeConditionDescription");
    expect(routeSource).toContain("resolveEdgeLanes");
    expect(routeSource).toContain("detectEdgeOverlap");
    expect(routeSource).toContain("arrowHeadPoints");
    expect(routeSource).toContain("edgeArrowHead");
    expect(routeSource).toContain("edgeTypeDescription");
    expect(routeSource).toContain("boundaryAnchor");
    expect(routeSource).toContain("EDGE_NODE_GAP");
    expect(routeSource).toContain("canvasZoom");
    expect(routeSource).toContain("PanState");
    expect(routeSource).toContain("canvasOffset");
    expect(routeSource).toContain("draftSignatureRef");
    expect(routeSource).toContain("远端画布已刷新");
    expect(routeSource).toContain("canvasViewportFromView");
    expect(routeSource).toContain("handleCanvasPointerDown");
    expect(routeSource).toContain("suppressCanvasClickRef");
    expect(routeSource).toContain("edgeVisualStyle");
    expect(routeSource).toContain("startEdgeReconnect");
    expect(routeSource).toContain("isValidEdgeReconnectTarget");
    expect(routeSource).toContain("正在重连");
    expect(routeSource).toContain("pushCanvasHistory");
    expect(routeSource).toContain("stepCanvasHistory");
    expect(routeSource).toContain("summarizeDeleteImpact");
    expect(routeSource).toContain("deleteCanvasSelection");
    expect(routeSource).toContain("shouldBlockCanvasLeave");
    expect(routeSource).toContain("saveMessage");
    expect(routeSource).toContain("handleCanvasWheel");
    expect(routeSource).toContain("preventDefault");
    expect(routeSource).toContain("画布缩放区域，滚轮可缩放画布");
    expect(routeSource).not.toContain("!event.ctrlKey && !event.metaKey");
    expect(routeSource).toContain("--research-flow-canvas-viewport-width");
    expect(routeSource).toContain("--research-flow-canvas-viewport-height");
    expect(routeSource).toContain("--research-flow-canvas-width");
    expect(routeSource).toContain("--research-flow-canvas-height");
    expect(routeSource).toContain("--research-flow-canvas-offset-x");
    expect(routeSource).toContain("--research-flow-canvas-offset-y");
    expect(routeSource).toContain("--research-flow-canvas-zoom");
    expect(routeSource).toContain("--research-flow-edge-stroke");
    expect(routeSource).toContain("--research-flow-edge-stroke-dasharray");
    expect(routeSource).toContain("--research-flow-edge-stroke-width");
    expect(routeSource).toContain("--research-flow-edge-fill");
    expect(routeSource).toContain("--research-flow-edge-label-left");
    expect(routeSource).toContain("--research-flow-edge-label-top");
    expect(routeSource).toContain("--research-flow-edge-endpoint-left");
    expect(routeSource).toContain("--research-flow-edge-endpoint-top");
    expect(routeSource).toContain("--research-flow-node-left");
    expect(routeSource).toContain("--research-flow-node-top");
    expect(routeSource).not.toContain("style={{ width: scaledCanvasWidth, height: scaledCanvasHeight }}");
    expect(routeSource).not.toContain("transform: `translate(${canvasOffset.x}px, ${canvasOffset.y}px) scale(${canvasZoom})`");
    expect(routeSource).not.toContain("stroke: visual.stroke");
    expect(routeSource).not.toContain("strokeDasharray: visual.strokeDasharray");
    expect(routeSource).not.toContain("strokeWidth: visual.strokeWidth");
    expect(routeSource).not.toContain("style={{ fill: visual.fill }}");
    expect(routeSource).not.toContain("style={{ left: geometry.label.x - 58, top: geometry.label.y - 16 }}");
    expect(routeSource).not.toContain("style={{ left: geometry.start.x - 8, top: geometry.start.y - 8 }}");
    expect(routeSource).not.toContain("style={{ left: geometry.end.x - 8, top: geometry.end.y - 8 }}");
    expect(routeSource).not.toContain("style={{ left: node.x, top: node.y }}");
    expect(routeSource).toContain("STATUS_OPTIONS");
    expect(routeSource).toContain("blocked");
    expect(routeSource).toContain("agentId");
    expect(routeSource).toContain("agentKey");
    expect(routeSource).toContain("llmConfigId");
    expect(routeSource).toContain("normalizeResearchFlowNodesForSave");
    expect(routeSource).toContain("styles.nodeTitleInput");
    expect(routeSource).not.toContain("旧节点级 LLM");
    expect(routeSource).toContain("routeCondition");
    expect(routeSource).toContain("condition: \"completed\"");
    expect(routeSource).not.toContain("executeMutation");
    expect(routeSource).not.toContain("researchThemeDiscoverySessions");
  });

  it("uses a full canvas plus inspector layout", () => {
    expect(styles.route).toBeTypeOf("string");
    expect(styles.route).toContain("grid-rows-[auto_auto_minmax(0,1fr)]");
    expect(styles.body).toContain("grid");
    expect(styles.body).toContain("h-full");
    expect(styles.body).toContain("min-h-0");
    expect(styles.body).toContain("grid-cols-[minmax(0,1fr)_clamp(300px,26vw,400px)]");
    expect(styles.body).toContain("overflow-hidden");
    expect(styles.canvasShell).toBeTypeOf("string");
    expect(styles.canvasShell).toContain("grid-rows-[auto_auto_minmax(0,1fr)]");
    expect(styles.canvasShell).toContain("overflow-hidden");
    expect(styles.canvasScroller).toBeTypeOf("string");
    expect(styles.canvasScroller).toContain("h-full");
    expect(styles.canvasScroller).toContain("overflow-auto");
    expect(styles.canvasViewport).toBeTypeOf("string");
    expect(styles.canvasViewport).toContain("min-h-full");
    expect(styles.canvasViewport).toContain("w-[var(--research-flow-canvas-viewport-width)]");
    expect(styles.canvasViewport).toContain("h-[var(--research-flow-canvas-viewport-height)]");
    expect(styles.canvasPanning).toBeTypeOf("string");
    expect(styles.canvas).toContain("w-[var(--research-flow-canvas-width)]");
    expect(styles.canvas).toContain("h-[var(--research-flow-canvas-height)]");
    expect(styles.canvas).toContain("[transform:translate(var(--research-flow-canvas-offset-x),var(--research-flow-canvas-offset-y))_scale(var(--research-flow-canvas-zoom))]");
    expect(styles.reconnectHint).toBeTypeOf("string");
    expect(styles.zoomControl).toBeTypeOf("string");
    expect(styles.iconButton).toBeTypeOf("string");
    expect(styles.node).toBeTypeOf("string");
    expect(styles.node).toContain("!absolute");
    expect(styles.node).toContain("left-[var(--research-flow-node-left)]");
    expect(styles.node).toContain("top-[var(--research-flow-node-top)]");
    expect(styles.nodeTitleInput).toBeTypeOf("string");
    expect(styles.nodeStatusCluster).toBeTypeOf("string");
    expect(styles.nodeWithIssue).toBeTypeOf("string");
    expect(styles.nodeIssueBadgeWarning).toBeTypeOf("string");
    expect(styles.edgeHotspot).toBeTypeOf("string");
    expect(styles.edgeHotspot).toContain("!absolute");
    expect(styles.edgeHotspot).toContain("left-[var(--research-flow-edge-label-left)]");
    expect(styles.edgeHotspot).toContain("top-[var(--research-flow-edge-label-top)]");
    expect(styles.edgeHotspotOffset).toBeTypeOf("string");
    expect(styles.edgeEndpointHandle).toBeTypeOf("string");
    expect(styles.edgeEndpointHandle).toContain("!absolute");
    expect(styles.edgeEndpointHandle).toContain("left-[var(--research-flow-edge-endpoint-left)]");
    expect(styles.edgeEndpointHandle).toContain("top-[var(--research-flow-edge-endpoint-top)]");
    expect(styles.edgeEndpointHandleActive).toBeTypeOf("string");
    expect(styles.edgeTrack).toBeTypeOf("string");
    expect(styles.edgePath).toBeTypeOf("string");
    expect(styles.edgePath).toContain("[stroke:var(--research-flow-edge-stroke)]");
    expect(styles.edgePath).toContain("[stroke-dasharray:var(--research-flow-edge-stroke-dasharray)]");
    expect(styles.edgePath).toContain("[stroke-width:var(--research-flow-edge-stroke-width)]");
    expect(styles.edgeArrowHead).toBeTypeOf("string");
    expect(styles.edgeArrowHead).toContain("[fill:var(--research-flow-edge-fill)]");
    expect(styles.edgeTypeHint).toBeTypeOf("string");
    expect(styles.saveStatusSuccess).toBeTypeOf("string");
    expect(styles.saveStatusWarning).toBeTypeOf("string");
    expect(styles.saveStatusError).toBeTypeOf("string");
    expect(styles.inspector).toBeTypeOf("string");
    expect(styles.inspector).toContain("grid-rows-[auto_minmax(0,1fr)]");
    expect(styles.inspector).toContain("h-full");
    expect(styles.inspector).toContain("overflow-hidden");
    expect(styles.inspectorBody).toBeTypeOf("string");
    expect(styles.inspectorBody).toContain("h-full");
    expect(styles.inspectorTabs).toBeTypeOf("string");
    expect(styles.inspectorTabs).toContain("overflow-auto");
    expect(styles.inspectorTab).toBeTypeOf("string");
    expect(styles.inspectorTabActive).toBeTypeOf("string");
    expect(styles.inspectorTabBadge).toBeTypeOf("string");
    expect(styles.inspectorContent).toBeTypeOf("string");
    expect(styles.inspectorContent).toContain("overflow-auto");
    expect(styles.issuePanel).toBeTypeOf("string");
    expect(styles.issueSummary).toBeTypeOf("string");
    expect(styles.issueCard).toBeTypeOf("string");
    expect(styles.issueCardBody).toBeTypeOf("string");
    expect(styles.organizationPanel).toBeTypeOf("string");
    expect(styles.organizationSummaryGrid).toBeTypeOf("string");
    expect(styles.organizationAgentCard).toBeTypeOf("string");
    expect(styles.organizationForm).toBeTypeOf("string");
    expect(styles.organizationProposalCard).toBeTypeOf("string");
    expect(styles.organizationAuditCard).toBeTypeOf("string");
    expect(styles.selectionSummary).toBeTypeOf("string");
    expect(styles.issueFocusButton).toBeTypeOf("string");
    expect(styles.issueEmpty).toBeTypeOf("string");
    expect(styles.executionBar).toBeTypeOf("string");
    expect(styles.observerStatus).toBeTypeOf("string");
    expect(styles.observerStatusActive).toBeTypeOf("string");
    expect(styles.lockButtonActive).toBeTypeOf("string");
    expect(styles.canvasLocked).toBeTypeOf("string");
    expect(styles.agentRoleTag).toBeTypeOf("string");
    expect(styles.agentRoleTag_research).toBeTypeOf("string");
    expect(styles.readonlyDetailHeader).toBeTypeOf("string");
    expect(styles.readonlySpecGrid).toBeTypeOf("string");
    expect(styles.readonlyDescription).toBeTypeOf("string");
    expect(styles.executionHint).toBeTypeOf("string");
    expect(styles.editorStack).toBeTypeOf("string");
    expect(styles.status_blocked).toBeTypeOf("string");
  });

  it("keeps route shells background-aware instead of restacking page surfaces", () => {
    expect(styles.route).not.toContain("bg-[var(--surface-page)]");
    expect(styles.canvasShell).not.toContain("bg-[var(--surface-page)]");
    expect(`${styles.route} ${styles.canvasShell}`).toMatch(/bg-transparent|bg-\[color-mix\(in_srgb,/);
  });

  it("keeps repeated issue and organization surfaces lighter than panel chrome", () => {
    [
      styles.issueCard,
      styles.issueCardBody,
      styles.issueCardHeader,
      styles.issueCardError,
      styles.issueCardWarning,
      styles.issueSummary,
      styles.issueSummaryError,
      styles.issueSummaryOk,
      styles.issueSummaryWarning,
      styles.organizationAgentCard,
      styles.organizationAuditCard,
      styles.organizationProposalCard,
      styles.organizationSummaryGrid,
    ].forEach(expectLightRepeatedSurface);

    expect(styles.issueCardError).toContain("var(--state-error)");
    expect(styles.issueCardWarning).toContain("var(--state-warning)");
    expect(styles.issueSummaryOk).toContain("var(--state-success)");
    expect(styles.organizationAgentCard).toContain("var(--accent-cool)");
  });

  it("keeps narrow inspector layouts inside local scroll boundaries", () => {
    expect(styles.body).toContain("max-[1080px]:grid-cols-1");
    expect(styles.body).toContain("overflow-hidden");
    expect(styles.canvasShell).toContain("min-w-0");
    expect(styles.canvasShell).toContain("overflow-hidden");
    expect(styles.canvasScroller).toContain("min-w-0");
    expect(styles.canvasScroller).toContain("overflow-auto");
    expect(styles.inspectorBody).toContain("min-w-0");
    expect(styles.inspectorBody).toContain("overflow-hidden");
    expect(styles.inspectorBody).toContain("max-[430px]:grid-cols-1");
    expect(styles.inspectorTabs).toContain("overflow-auto");
    expect(styles.inspectorContent).toContain("overflow-auto");
    expect(styles.issueSummary).toContain("max-[430px]:grid-cols-1");
    expect(styles.organizationSummaryGrid).toContain("max-[430px]:grid-cols-1");
    expect(styles.twoColumns).toContain("max-[430px]:grid-cols-1");
  });

  it("keeps canvas inspector surfaces background-aware and horizontally contained", () => {
    for (const key of [
      "body",
      "canvasShell",
      "inspector",
      "inspectorHeader",
      "inspectorContent",
      "issuePanel",
      "issueCard",
      "issueCardBody",
      "issueCardHeader",
      "issueSummary",
      "organizationPanel",
      "organizationActionRow",
      "organizationAuditCard",
      "organizationBadgeRow",
      "organizationMetric",
      "organizationProposalCard",
      "organizationSummaryGrid",
      "readonlyDetailHeader",
      "selectionSummary",
    ] as const) {
      expect(styles[key], key).toContain("min-w-0");
      expect(styles[key], key).toContain("max-w-full");
    }

    for (const key of [
      "canvasShell",
      "issuePanel",
      "issueCard",
      "issueCardBody",
      "issueCardHeader",
      "issueSummary",
      "organizationPanel",
      "organizationActionRow",
      "organizationAuditCard",
      "organizationBadgeRow",
      "organizationMetric",
      "organizationProposalCard",
      "organizationSummaryGrid",
      "readonlyDetailHeader",
      "selectionSummary",
    ] as const) {
      expect(styles[key], key).toMatch(/vui-surface-|color-mix\(in_srgb/);
      expect(styles[key], key).not.toContain("bg-[var(--vui-surface-glass)]");
      expect(styles[key], key).not.toContain("bg-[var(--surface-page)]");
    }

    expect(styles.body).toContain("overflow-x-hidden");
    expect(styles.inspector).toContain("overflow-x-hidden");
    expect(styles.inspectorContent).toContain("overflow-x-hidden");
    expect(styles.selectionSummary).toContain("[overflow-wrap:anywhere]");
    expect(styles.primaryButton).toMatch(/bg-\[|!bg-\[|var\(--vui-surface/);
    expect(styles.primaryButton).not.toContain("var(--vui-surface-row)");
  });

  it("keeps restored canvas inspector grids from the CSS module migration", () => {
    expect(routeSource).toContain("styles.inspectorBody");
    expect(styles.inspectorBody).toContain("grid-cols-[76px_minmax(0,1fr)]");
    expect(styles.inspectorBody).toContain("max-[430px]:grid-cols-1");
    expect(styles.inspectorBody).toContain("overflow-hidden");

    expect(routeSource).toContain("styles.organizationSummaryGrid");
    expect(styles.organizationSummaryGrid).toContain("grid-cols-[repeat(3,minmax(0,1fr))]");
    expect(styles.organizationSummaryGrid).toContain("gap-2");
    expect(styles.organizationSummaryGrid).toContain("max-[430px]:grid-cols-1");

    expect(routeSource).toContain("styles.organizationMetric");
    expect(styles.organizationMetric).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(styles.organizationMetric).toContain("gap-x-2");

    expect(routeSource).toContain("styles.issueSummary");
    expect(styles.issueSummary).toContain("grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(styles.issueSummary).toContain("max-[430px]:grid-cols-1");

    expect(routeSource).toContain("styles.readonlySpecGrid");
    expect(styles.readonlySpecGrid).toContain("grid-cols-[auto_minmax(0,1fr)]");
    expect(styles.readonlySpecGrid).toContain("gap-y-[7px]");

    expect(routeSource).toContain("styles.twoColumns");
    expect(styles.twoColumns).toContain("grid-cols-[repeat(2,minmax(0,1fr))]");
    expect(styles.twoColumns).toContain("max-[430px]:grid-cols-1");

    expect(routeSource).toContain("styles.edgePair");
    expect(styles.edgePair).toContain("grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)]");
    expect(styles.edgePair).toContain("items-center");
  });
});
