/**
 * Test-only browser handshake for the production workflow ELK Worker.
 *
 * It deliberately imports the same worker client as the canvas and reports
 * back to the runner after an actual asynchronous layout. This is not a
 * product route and is excluded from the normal Vite build.
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import { createWorkflowLayoutEngine } from "../src/components/vui/renderers/shadcn/workflow/workflowElkClient";
import { resolveEdgeLabelSpec } from "../src/components/vui/renderers/shadcn/workflow/workflowEdgeLabelGeometry";

type HandshakeReport = {
  ok: boolean;
  workerUrl: string | null;
  worker: {
    constructCount: number;
    terminateCount: number;
    constructedAfterTerminate: boolean;
    urlMatchesWorkerAsset: boolean;
  };
  engine: {
    nodeCount: number;
    haveNodeCoordinates: boolean;
    edgeCount: number;
    haveEdgeSections: boolean;
    edgeLabelHaveCoordinates: boolean;
  };
  afterTerminateBehavior: "rejected" | "timeout" | "still-resolved";
  fallbackBundledDetected: boolean;
  errors: string[];
};

const report: HandshakeReport = {
  ok: false,
  workerUrl: null,
  worker: {
    constructCount: 0,
    terminateCount: 0,
    constructedAfterTerminate: false,
    urlMatchesWorkerAsset: false,
  },
  engine: {
    nodeCount: 0,
    haveNodeCoordinates: false,
    edgeCount: 0,
    haveEdgeSections: false,
    edgeLabelHaveCoordinates: false,
  },
  afterTerminateBehavior: "timeout",
  fallbackBundledDetected: false,
  errors: [],
};

function minCompoundGraph(): ElkNode {
  const label = resolveEdgeLabelSpec("同协议重跑");
  return {
    id: "probe:root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.edgeRouting": "ORTHOGONAL",
    },
    children: [
      {
        id: "stage:execution",
        layoutOptions: {
          "elk.direction": "DOWN",
          "elk.padding": "[top=56,left=12,bottom=28,right=12]",
        },
        children: [
          {
            id: "controlled_run",
            width: 248,
            height: 88,
            ports: [
              {
                id: "feedback:in:controlled_run",
                layoutOptions: { "elk.port.side": "EAST" },
              },
            ],
          },
          {
            id: "iteration_decision",
            width: 248,
            height: 112,
            ports: [
              {
                id: "decision:rerun:iteration_decision",
                layoutOptions: { "elk.port.side": "WEST" },
              },
            ],
          },
        ],
        edges: [
          {
            id: "probe:rerun",
            sources: ["decision:rerun:iteration_decision"],
            targets: ["feedback:in:controlled_run"],
            labels: [{ ...label, layoutOptions: { "elk.edgeLabels.placement": "CENTER" } }],
          },
        ],
      },
    ],
  };
}

function instrumentWorker(): void {
  const OriginalWorker = window.Worker;
  const state = { terminated: false };
  window.Worker = class extends OriginalWorker {
    constructor(...args: ConstructorParameters<typeof OriginalWorker>) {
      report.worker.constructCount += 1;
      report.worker.constructedAfterTerminate ||= state.terminated;
      const workerUrl = String(args[0]);
      report.workerUrl = workerUrl;
      report.worker.urlMatchesWorkerAsset =
        /\/assets\/elk-worker(?:\.min)?-[\w-]+\.js(?:\?.*)?$/.test(workerUrl);
      super(...args);
    }

    terminate(): void {
      report.worker.terminateCount += 1;
      state.terminated = true;
      super.terminate();
    }
  };
}

async function run(): Promise<void> {
  try {
    instrumentWorker();
    const engine = createWorkflowLayoutEngine();
    const graph = minCompoundGraph();
    const output = await engine.layout(graph);
    const nodes = (output.children ?? []).flatMap((stage) => [stage, ...(stage.children ?? [])]);
    const edges = [
      ...(output.edges ?? []),
      ...(output.children ?? []).flatMap((stage) => stage.edges ?? []),
    ];

    report.engine.nodeCount = nodes.length;
    report.engine.haveNodeCoordinates =
      nodes.length > 0 && nodes.every((node) => Number.isFinite(node.x) && Number.isFinite(node.y));
    report.engine.edgeCount = edges.length;
    report.engine.haveEdgeSections =
      edges.length > 0 && edges.every((edge) => (edge.sections?.length ?? 0) > 0);
    report.engine.edgeLabelHaveCoordinates =
      edges.length > 0 &&
      edges.every(
        (edge) =>
          (edge.labels?.length ?? 0) === 0 ||
          (Number.isFinite(edge.labels?.[0]?.x) && Number.isFinite(edge.labels?.[0]?.y)),
      );

    engine.terminate();
    report.afterTerminateBehavior = await Promise.race([
      engine.layout(graph).then(
        () => "still-resolved" as const,
        () => "rejected" as const,
      ),
      new Promise<"timeout">((resolve) => window.setTimeout(() => resolve("timeout"), 1200)),
    ]);
    report.fallbackBundledDetected =
      report.worker.constructCount === 0 || !report.worker.urlMatchesWorkerAsset;
    report.ok =
      report.workerUrl !== null &&
      report.worker.constructCount === 1 &&
      report.worker.terminateCount >= 1 &&
      !report.worker.constructedAfterTerminate &&
      report.worker.urlMatchesWorkerAsset &&
      !report.fallbackBundledDetected &&
      report.engine.haveNodeCoordinates &&
      report.engine.haveEdgeSections &&
      report.engine.edgeLabelHaveCoordinates &&
      report.afterTerminateBehavior !== "still-resolved";
  } catch (error) {
    report.errors.push(String(error instanceof Error ? error.message : error));
  }

  const result = document.getElementById("result");
  if (!result) {
    throw new Error("workflow ELK handshake probe is missing #result");
  }
  result.textContent = JSON.stringify(report);
  await fetch("/__handshake_result", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(report),
  });
}

void run().catch((error) => {
  report.errors.push(String(error instanceof Error ? error.message : error));
  const result = document.getElementById("result");
  if (result) result.textContent = JSON.stringify(report);
});
