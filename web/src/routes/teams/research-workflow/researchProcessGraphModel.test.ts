import { describe, expect, it } from "vitest";

import type { WorkflowCanvasProjection, WorkflowDefinition } from "../../../api/types/researchWorkflow";
import {
  buildHypothesisFirstCanvasRegion,
  type HypothesisFirstCanvasRegionInput,
} from "./hypothesisFirstCanvasRegion";
import {
  composeHypothesisFirstGraph,
  definitionToCanvasGraph,
  mergeSelectionAndRuntime,
  projectionToCanvasGraph,
} from "./researchProcessGraphModel";

const definition: WorkflowDefinition = {
  workflowId: "challenge-cup-research",
  schemaVersion: "1",
  label: "挑战杯",
  structureHash: "h",
  stages: [
    {
      stageId: "knowledge_collection",
      index: 0,
      label: "知识搜集",
      nodeIds: ["source_finding", "knowledge_handoff"],
    },
    {
      stageId: "experiment_design",
      index: 1,
      label: "实验设计",
      nodeIds: ["hypothesis_design"],
    },
    {
      stageId: "execution_iteration",
      index: 2,
      label: "执行迭代",
      nodeIds: ["iteration_decision", "result_package"],
    },
  ],
  nodes: [
    {
      nodeId: "source_finding",
      stageId: "knowledge_collection",
      label: "资料寻找",
      actorKind: "agent",
      primaryRoleKey: "finder",
      description: "find sources",
      producesArtifactKinds: ["source_candidate_batch"],
    },
    {
      nodeId: "knowledge_handoff",
      stageId: "knowledge_collection",
      label: "知识包交接",
      actorKind: "human",
      primaryRoleKey: "human",
      acceptsGateKinds: ["human"],
    },
    {
      nodeId: "hypothesis_design",
      stageId: "experiment_design",
      label: "假设设计",
      actorKind: "agent",
      primaryRoleKey: "scientist",
    },
    {
      nodeId: "iteration_decision",
      stageId: "execution_iteration",
      label: "迭代决策",
      actorKind: "agent",
      primaryRoleKey: "decider",
    },
    {
      nodeId: "result_package",
      stageId: "execution_iteration",
      label: "结果打包",
      actorKind: "system",
      primaryRoleKey: "package_builder",
    },
  ],
  edges: [
    {
      edgeId: "e_find_handoff",
      fromNodeId: "source_finding",
      toNodeId: "knowledge_handoff",
      label: "候选",
      gateKind: "auto",
    },
    {
      edgeId: "e_kc_hypothesis",
      fromNodeId: "knowledge_handoff",
      toNodeId: "hypothesis_design",
      label: "Knowledge Package",
      gateKind: "knowledge_package",
      requiresHumanAccept: true,
      requiredArtifactKinds: ["knowledge_package"],
    },
    {
      edgeId: "e_decision_rerun",
      fromNodeId: "iteration_decision",
      toNodeId: "result_package",
      label: "同协议重跑",
      gateKind: "auto",
    },
    {
      edgeId: "e_decision_promo",
      fromNodeId: "iteration_decision",
      toNodeId: "result_package",
      label: "晋升提案",
      gateKind: "promotion",
      requiresHumanAccept: true,
    },
  ],
};

describe("researchProcessGraphModel", () => {
  it("definition maps visual kinds and edge gate metadata", () => {
    const graph = definitionToCanvasGraph(definition);
    expect(graph.nodes.find((n) => n.nodeId === "source_finding")?.visualKind).toBe("start");
    expect(graph.nodes.find((n) => n.nodeId === "knowledge_handoff")?.visualKind).toBe("human_gate");
    expect(graph.nodes.find((n) => n.nodeId === "iteration_decision")?.visualKind).toBe("decision");
    expect(graph.nodes.find((n) => n.nodeId === "result_package")?.visualKind).toBe("end");
    const handoff = graph.edges.find((e) => e.edgeId === "e_kc_hypothesis");
    expect(handoff?.gateKind).toBe("knowledge_package");
    expect(handoff?.requiresHumanAccept).toBe(true);
    expect(handoff?.requiredArtifactKinds).toEqual(["knowledge_package"]);
    expect(handoff?.semanticKind).toBe("human_gate");
    expect(handoff?.labelAlwaysVisible).toBe(true);
    const rerun = graph.edges.find((e) => e.edgeId === "e_decision_rerun");
    expect(rerun?.semanticKind).toBe("rerun");
    expect(rerun?.sourceHandle).toBe("rerun");
  });

  it("keeps a queued run cursor as pending instead of painting it running", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-queued",
        status: "queued",
        runtimeCurrentNodeIds: ["source_finding"],
        nodeRuns: {
          source_finding: {
            nodeId: "source_finding",
            status: "pending",
            attempt: 0,
            actorKind: "agent",
          },
        },
        pendingHumanTasks: [],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
        iterationBudgetMax: 3,
      },
    };
    const graph = projectionToCanvasGraph(projection);
    const finding = graph.nodes.find((n) => n.nodeId === "source_finding");
    expect(finding?.status).toBe("pending");
    expect(finding?.isRuntimeCurrent).toBe(true);
    expect(graph.stages.find((stage) => stage.stageId === "knowledge_collection")?.stageTone).toBe("idle");
  });

  it("projects effective Agent bindings before a run exists", () => {
    const graph = definitionToCanvasGraph(definition, {
      primaryAgentIdByNode: new Map([["source_finding", "agent-finder"]]),
    });
    expect(graph.nodes.find((node) => node.nodeId === "source_finding")?.primaryAgentId).toBe("agent-finder");
    expect(graph.nodes.find((node) => node.nodeId === "knowledge_handoff")?.primaryAgentId).toBeUndefined();
  });

  it("projection keeps nodeRuns status, attempt, agent and human tasks", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-1",
        status: "waiting_human",
        runtimeCurrentNodeIds: ["knowledge_handoff"],
        nodeRuns: {
          source_finding: {
            nodeId: "source_finding",
            status: "succeeded",
            attempt: 1,
            primaryAgentId: "agent-finder",
            actorKind: "agent",
          },
          knowledge_handoff: {
            nodeId: "knowledge_handoff",
            status: "waiting_human",
            attempt: 1,
            actorKind: "human",
          },
          hypothesis_design: {
            nodeId: "hypothesis_design",
            status: "pending",
            attempt: 0,
          },
        },
        pendingHumanTasks: [{ taskId: "t1", nodeId: "knowledge_handoff", status: "pending" }],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
        iterationBudgetMax: 3,
      },
    };
    const graph = projectionToCanvasGraph(projection);
    const finding = graph.nodes.find((n) => n.nodeId === "source_finding");
    const handoff = graph.nodes.find((n) => n.nodeId === "knowledge_handoff");
    expect(finding?.status).toBe("succeeded");
    expect(finding?.attempt).toBe(1);
    expect(finding?.primaryAgentId).toBe("agent-finder");
    expect(finding?.description).toBe("find sources");
    expect(handoff?.status).toBe("waiting_human");
    expect(handoff?.isRuntimeCurrent).toBe(true);
    expect(handoff?.hasPendingHumanTask).toBe(true);
    expect(graph.run?.runId).toBe("run-1");
    expect(graph.run?.iterationBudgetMax).toBe(3);
    expect(graph.run?.runtimeCurrentNodeIds).toEqual(["knowledge_handoff"]);
    // selected never on graph
    expect(JSON.stringify(graph)).not.toContain("selectedNodeId");
  });

  it("overlays effective Agent bindings when a run projection omits primaryAgentId", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-3",
        status: "running",
        runtimeCurrentNodeIds: ["source_finding"],
        nodeRuns: {
          source_finding: {
            nodeId: "source_finding",
            status: "running",
            attempt: 1,
            actorKind: "agent",
          },
        },
        pendingHumanTasks: [],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
      },
    };
    const graph = projectionToCanvasGraph(projection, {
      primaryAgentIdByNode: new Map([["source_finding", "agent-finder"]]),
    });
    expect(graph.nodes.find((node) => node.nodeId === "source_finding")?.primaryAgentId).toBe(
      "agent-finder",
    );
  });

  it("maps blocked and failed without collapsing them", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-2",
        status: "blocked",
        runtimeCurrentNodeIds: ["hypothesis_design"],
        nodeRuns: {
          hypothesis_design: {
            nodeId: "hypothesis_design",
            status: "blocked",
            attempt: 2,
          },
        },
        pendingHumanTasks: [],
        blockedReason: "缺少 Knowledge Package",
      },
    };
    const graph = projectionToCanvasGraph(projection);
    const node = graph.nodes.find((n) => n.nodeId === "hypothesis_design");
    expect(node?.status).toBe("blocked");
    expect(node?.blockedReason).toContain("Knowledge Package");
    expect(node?.attempt).toBe(2);
  });

  it("keeps selection and runtime independent", () => {
    const merged = mergeSelectionAndRuntime({
      selectedNodeId: "hypothesis_design",
      runtimeCurrentNodeIds: ["knowledge_handoff"],
    });
    expect(merged.selectedNodeId).toBe("hypothesis_design");
    expect(merged.runtimeCurrentNodeIds).toEqual(["knowledge_handoff"]);
    expect(merged.selectedNodeId).not.toBe(merged.runtimeCurrentNodeIds[0]);
  });
});

describe("composeHypothesisFirstGraph", () => {
  const hfScope = {
    program: "p",
    theme: "t",
    campaign: "c",
    question: "Q-01",
    branch: "b",
    workflow: "w",
    agentId: "a",
  };

  function regionInput(overrides: Partial<HypothesisFirstCanvasRegionInput> = {}): HypothesisFirstCanvasRegionInput {
    return {
      chainState: {
        schemaVersion: 1,
        teamId: "team-1",
        questionId: "Q-01",
        selectionId: "sel-1",
        meetingCount: 1,
        firstMeetingId: "hf-review-sel-1-r1",
        firstMeetingClosed: true,
        openMeetingIds: [],
        collectionRequests: [],
        collectionRequestCount: 0,
        pendingCollectionCount: 0,
        collectionReady: false,
        hypothesisRoundCount: 0,
        latestHypothesisRoundId: "",
        hypothesisConverged: false,
        convergenceDetail: "",
        roundBudget: 3,
        budgetExhausted: false,
        templateBaselineExists: false,
        templateBaselineIds: [],
      },
      meetings: [
        {
          ...hfScope,
          schemaVersion: 1,
          meetingRoundId: "hf-review-sel-1-r1",
          meetingType: "hypothesis_review",
          mode: "review",
          scopeHash: "sh",
          participants: ["agent-1"],
          status: "closed",
          startedAt: "2026-08-19T01:00:00Z",
          closedAt: "2026-08-19T02:00:00Z",
          digestRef: "digest-1",
          roundIndex: 1,
        },
      ],
      collectionRequests: [],
      reviewRoundLinks: [],
      selection: {
        ...hfScope,
        schemaVersion: 1,
        selectionId: "sel-1",
        selectionHash: "h",
        mode: "manual",
        scopeHash: "sh",
        questionId: "Q-01",
        selectedCandidateIds: ["cand-1"],
        previousSelectionId: "",
        decidedBy: "leader",
        createdAt: "2026-08-19T00:00:00Z",
      },
      ...overrides,
    };
  }

  it("returns the base graph untouched when the region is null", () => {
    const base = definitionToCanvasGraph(definition);
    const composed = composeHypothesisFirstGraph(base, null);
    expect(composed).toBe(base);
    expect(composed.stages.map((stage) => stage.stageId)).toEqual([
      "knowledge_collection",
      "experiment_design",
      "execution_iteration",
    ]);
  });

  it("inserts the region stage at index 0 and shifts existing stages", () => {
    const base = definitionToCanvasGraph(definition);
    const region = buildHypothesisFirstCanvasRegion(regionInput())!;
    const composed = composeHypothesisFirstGraph(base, region);

    expect(composed.stages.map((stage) => stage.stageId)).toEqual([
      "hypothesis_first",
      "knowledge_collection",
      "experiment_design",
      "execution_iteration",
    ]);
    expect(composed.stages.map((stage) => stage.index)).toEqual([0, 1, 2, 3]);
    expect(composed.stages[0]).toMatchObject({ label: "假说先行", progress: { completed: 2, total: 3 } });

    // Region cards come first; base nodes keep their identity.
    expect(composed.nodes.map((node) => node.nodeId)).toEqual([
      "hf_selection",
      "hf_meeting_1",
      "hf_convergence_gate",
      ...base.nodes.map((node) => node.nodeId),
    ]);
    expect(composed.nodes.find((node) => node.nodeId === "hf_meeting_1")?.status).toBe("succeeded");

    // Gate edges land on the main graph entry points.
    const stage1 = composed.edges.find((edge) => edge.edgeId === "hf_e_m1_stage1")!;
    expect(stage1).toMatchObject({
      fromNodeId: "hf_meeting_1",
      toNodeId: "source_finding",
      label: "首轮搜集范围就绪",
      semanticKind: "human_gate",
    });
    const stage2 = composed.edges.find((edge) => edge.edgeId === "hf_e_gate_stage2")!;
    expect(stage2).toMatchObject({
      fromNodeId: "hf_convergence_gate",
      toNodeId: "hypothesis_design",
      label: "假说集就绪",
      semanticKind: "human_gate",
    });
    // Base edges stay intact after the region edges.
    expect(composed.edges.slice(region.edges.length)).toEqual(base.edges);
  });

  it("re-resolves gate edge pathState against the full graph (traversed needs both sides)", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-hf",
        status: "running",
        runtimeCurrentNodeIds: ["source_finding"],
        nodeRuns: {
          source_finding: { nodeId: "source_finding", status: "running", attempt: 1, actorKind: "agent" },
        },
        pendingHumanTasks: [],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
      },
    };
    const base = projectionToCanvasGraph(projection);
    const region = buildHypothesisFirstCanvasRegion(regionInput())!;

    // Inside the isolated fragment the external endpoint is unknown (pending),
    // so a succeeded meeting alone cannot mark the gate edge traversed.
    const isolated = region.edges.find((edge) => edge.edgeId === "hf_e_m1_stage1")!;
    expect(isolated.pathState).toBe("idle");

    const composed = composeHypothesisFirstGraph(base, region);
    const gateEdge = composed.edges.find((edge) => edge.edgeId === "hf_e_m1_stage1")!;
    // source_finding is runtime-current → the readiness edge turns active.
    expect(gateEdge.pathState).toBe("active");
  });

  it("drops region edges whose endpoints are missing from the base graph", () => {
    const base = definitionToCanvasGraph({
      ...definition,
      nodes: definition.nodes.filter((node) => node.nodeId !== "hypothesis_design"),
      stages: definition.stages.map((stage) =>
        stage.stageId === "experiment_design" ? { ...stage, nodeIds: [] } : stage),
      edges: definition.edges.filter((edge) => edge.toNodeId !== "hypothesis_design"),
    });
    const region = buildHypothesisFirstCanvasRegion(regionInput())!;
    const composed = composeHypothesisFirstGraph(base, region);
    expect(composed.edges.some((edge) => edge.edgeId === "hf_e_gate_stage2")).toBe(false);
    expect(composed.edges.some((edge) => edge.edgeId === "hf_e_m1_stage1")).toBe(true);
  });

  it("demotes 16-node stage tones while a hypothesis-first discussion is live", () => {
    const projection: WorkflowCanvasProjection = {
      definition,
      run: {
        runId: "run-hf",
        status: "running",
        runtimeCurrentNodeIds: ["source_finding"],
        nodeRuns: {
          source_finding: { nodeId: "source_finding", status: "running", attempt: 1, actorKind: "agent" },
        },
        pendingHumanTasks: [],
        blockedReason: null,
        completionKind: "",
        parentRunId: null,
        childRunIds: [],
      },
    };
    const base = projectionToCanvasGraph(projection);
    const region = buildHypothesisFirstCanvasRegion(regionInput({
      meetings: [{
        ...hfScope,
        schemaVersion: 1,
        meetingRoundId: "hf-review-sel-1-r1",
        meetingType: "hypothesis_review",
        mode: "review",
        scopeHash: "sh",
        participants: ["agent-1"],
        status: "open",
        startedAt: "2026-08-19T01:00:00Z",
        roundIndex: 1,
      }],
    }))!;
    const composed = composeHypothesisFirstGraph(base, region, { demotePipelineStages: true });
    expect(composed.stages[0]?.stageId).toBe("hypothesis_first");
    expect(composed.stages[0]?.stageTone).toBe("active");
    expect(composed.stages.filter((stage) => stage.stageId !== "hypothesis_first").every((stage) => stage.stageTone === "idle")).toBe(true);
  });

  it("omits the idle 16-node pipeline until a review round has closed", () => {
    const base = definitionToCanvasGraph(definition);
    const region = buildHypothesisFirstCanvasRegion(regionInput({
      meetings: [],
      chainState: {
        schemaVersion: 1,
        teamId: "team-1",
        questionId: "Q-01",
        selectionId: "sel-1",
        meetingCount: 0,
        firstMeetingId: "",
        firstMeetingClosed: false,
        openMeetingIds: [],
        collectionRequests: [],
        collectionRequestCount: 0,
        pendingCollectionCount: 0,
        collectionReady: false,
        hypothesisRoundCount: 0,
        latestHypothesisRoundId: "",
        hypothesisConverged: false,
        convergenceDetail: "",
        roundBudget: 3,
        budgetExhausted: false,
        templateBaselineExists: false,
        templateBaselineIds: [],
      },
    }))!;
    expect(region.showDownstreamPipeline).toBe(false);
    const composed = composeHypothesisFirstGraph(base, region, { demotePipelineStages: true });
    expect(composed.stages.map((stage) => stage.stageId)).toEqual(["hypothesis_first"]);
    expect(composed.nodes.map((node) => node.nodeId)).toEqual(["hf_selection"]);
    expect(composed.edges).toEqual([]);
    expect(composed.stages[0]?.stageTone).toBe("done");
  });
});
