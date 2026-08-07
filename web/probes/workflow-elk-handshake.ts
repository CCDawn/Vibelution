/**
 * Browser-only handshake for the production ELK Worker engine.
 *
 * This is a build-time TEST ENTRY: `?worker` and the engine factory must be
 * reachable from a module that is actually built, otherwise Vite emits no
 * worker asset. It is deliberately separate from the VUI product surface —
 * it mounts no React, touches no Route, and only exercises
 * `workflowElkClient`.
 *
 * It proves, in a real browser against the production-build worker asset:
 *   1. the Worker asset is loadable and `elk.layout` resolves coordinates +
 *      edge sections from it;
 *   2. exactly one Worker is constructed from the real `elk-worker.min-*`
 *      asset, `terminate()` was actually invoked, and no new Worker appears
 *      after terminate (no orphan worker keeps accepting messages);
 *   3. no main-thread bundled-ELK fallback exists on this path (zero
 *      Worker constructions or a non-worker URL fails the gate).
 *
 * The result is rendered as text into `#result` and POSTed to
 * `/__handshake_result` for the headless runner (real asynchronous timing;
 * `--dump-dom` cannot wait for Worker replies).
 */
import type { ElkNode } from "elkjs/lib/elk-api";

import { createWorkflowLayoutEngine } from "../src/components/vui/renderers/shadcn/workflow/workflowElkClient";

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

function minCompoundElkNode(): ElkNode {
  return {
    id: "probe:root",
    layoutOptions: {
      "elk.algorithm": "layered",
      "elk.direction": "RIGHT",
      "elk.hierarchyHandling": "INCLUDE_CHILDREN",
      "elk.edgeRouting": "ORTHOGONAL",
      "elk.portConstraints": "FIXED_SIDE",
    },
    children: [
      {
        id: "stage:execution",
        width: 500,
        height: 260,
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
            id: "probe:e_rerun",
            sources: ["decision:rerun:iteration_decision"],
            targets: ["feedback:in:controlled_run"],
            labels: [
              {
                text: "同协议重跑",
                width: 152,
                height: 24,
                layoutOptions: { "elk.edgeLabels.placement": "CENTER" },
              },
            ],
          },
        ],
      },
    ],
  };
}

function recordWorkerUrl(): void {
  const OriginalWorker = window.Worker;
  const state: { terminated: boolean } = { terminated: false };
  (window as unknown as { __elkWorkerUrl?: string }).__elkWorkerUrl = null as unknown as string;
  window.Worker = class extends OriginalWorker {
    constructor(...args: ConstructorParameters<typeof OriginalWorker>) {
      report.worker.constructCount += 1;
      if (state.terminated) {
        report.worker.constructedAfterTerminate = true;
      }
      const url = String(args[0]);
      (window as unknown as { __elkWorkerUrl?: string }).__elkWorkerUrl = url;
      report.workerUrl = url;
      report.worker.urlMatchesWorkerAsset = /elk-worker\.min-.*\.js$/.test(url);
      super(...args);
    }

    terminate(): void {
      report.worker.terminateCount += 1;
      state.terminated = true;
      super.terminate();
    }
  };
}

async function main(reportEl: HTMLElement): Promise<void> {
  try {
    recordWorkerUrl();
    const engine = createWorkflowLayoutEngine();

    const graph = minCompoundElkNode();
    const out = await engine.layout(graph);

    const allNodes = (out.children ?? []).flatMap((stage) => [
      stage,
      ...(stage.children ?? []),
    ]);
    report.engine.nodeCount = allNodes.length;
    report.engine.haveNodeCoordinates = allNodes.every(
      (n) => Number.isFinite(n.x) && Number.isFinite(n.y),
    );
    const allEdges = [
      ...(out.edges ?? []),
      ...(out.children ?? []).flatMap((s) => s.edges ?? []),
    ];
    report.engine.edgeCount = allEdges.length;
    report.engine.haveEdgeSections =
      allEdges.length > 0 && allEdges.every((e) => (e.sections?.length ?? 0) > 0);
    report.engine.edgeLabelHaveCoordinates =
      allEdges.length > 0 &&
      allEdges.every(
        (e) =>
          (e.labels?.length ?? 0) === 0 ||
          (Number.isFinite(e.labels?.[0]?.x) && Number.isFinite(e.labels?.[0]?.y)),
      );

    report.workerUrl =
      (window as unknown as { __elkWorkerUrl?: string }).__elkWorkerUrl ?? null;

    engine.terminate();
    const afterWait = await Promise.race([
      engine.layout(graph).then(
        () => "still-resolved" as const,
        () => "rejected" as const,
      ),
      new Promise<"timeout">((resolve) => setTimeout(() => resolve("timeout"), 2500)),
    ]);
    report.afterTerminateBehavior = afterWait;

    // The engine must have constructed exactly one Worker from the real
    // production asset; no second Worker may appear after terminate().
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
    report.ok = false;
    report.errors.push(String((error as Error)?.message ?? error));
  }

  reportEl.textContent = JSON.stringify(report, null, 2);

  // Push the machine-readable result back so the headless runner can read it
  // with real asynchronous timing (dump-dom cannot wait for Worker replies).
  try {
    await fetch("/__handshake_result", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(report),
    });
  } catch {
    // DOM text remains the fallback source of truth.
  }
}

const pre = document.getElementById("result");
if (pre) {
  pre.textContent = "module-loaded";
  void main(pre);
} else {
  // Nothing on this page can proceed without the host element.
  throw new Error("missing #result element");
}
