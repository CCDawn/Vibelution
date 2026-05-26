import { describe, expect, it } from "vitest";

import styles from "./ResearchFlowCanvasRoute.module.css";
import routeSource from "./ResearchFlowCanvasRoute.tsx?raw";
import routerSource from "../app/router.tsx?raw";

describe("ResearchFlowCanvasRoute layout contract", () => {
  it("exposes a dedicated API-backed research flow canvas page", () => {
    expect(routerSource).toContain("ResearchFlowCanvasRoute");
    expect(routerSource).toContain("research/flow-canvas");
    expect(routeSource).toContain("/api/research/flow-canvas");
    expect(routeSource).toContain("Research Flow Canvas");
    expect(routeSource).toContain("科研流程画布");
    expect(routeSource).toContain("workspace/prompts/research/flow_canvas.json");
  });

  it("keeps the canvas editable as a graph instead of a fixed stage rail", () => {
    expect(routeSource).toContain("addNode");
    expect(routeSource).toContain("deleteSelected");
    expect(routeSource).toContain("handleNodePointerDown");
    expect(routeSource).toContain("connect.sourceId");
    expect(routeSource).toContain("nextEdgeId");
    expect(routeSource).toContain("STATUS_OPTIONS");
    expect(routeSource).toContain("needs_evidence");
    expect(routeSource).toContain("blocked");
    expect(routeSource).toContain("agentKey");
    expect(routeSource).toContain("llmConfigId");
    expect(routeSource).toContain("routeCondition");
  });

  it("uses a full canvas plus inspector layout", () => {
    expect(styles.route).toBeTypeOf("string");
    expect(styles.canvasShell).toBeTypeOf("string");
    expect(styles.canvasScroller).toBeTypeOf("string");
    expect(styles.node).toBeTypeOf("string");
    expect(styles.edgeHotspot).toBeTypeOf("string");
    expect(styles.inspector).toBeTypeOf("string");
    expect(styles.editorStack).toBeTypeOf("string");
    expect(styles.status_needs_evidence).toBeTypeOf("string");
    expect(styles.status_blocked).toBeTypeOf("string");
  });
});
