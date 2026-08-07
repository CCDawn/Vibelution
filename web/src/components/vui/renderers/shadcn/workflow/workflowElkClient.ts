/**
 * ELK layout engine client for the workflow canvas.
 *
 * Production uses the Vite `?worker` build of `elkjs` and a fixed
 * `workerFactory`; tests inject a bundled-ELK engine instead. The hook never
 * constructs a Worker directly — it consumes the `WorkflowLayoutEngine`
 * interface defined here.
 *
 * Lifecycle: one engine per canvas lifecycle, `terminate()` on unmount so
 * React StrictMode mount/cleanup/remount leaves no orphan Worker.
 */
import ELK from "elkjs/lib/elk-api";
import ElkWorker from "elkjs/lib/elk-worker.min.js?worker";
import type { ElkNode } from "elkjs/lib/elk-api";

/**
 * Minimal layout-engine seam shared by the bundled (tests) and the
 * Worker (production) implementations.
 */
export type WorkflowLayoutEngine = {
  layout(graph: ElkNode): Promise<ElkNode>;
  /** Release worker/global resources; engine is unusable afterwards. */
  terminate(): void;
};

export function createWorkflowLayoutEngine(): WorkflowLayoutEngine {
  const elk = new ELK({
    workerFactory: () => new ElkWorker(),
  });
  return {
    // The graph already carries its layoutOptions (workflowElkGraphAdapter);
    // the engine only executes the layout.
    layout(graph: ElkNode): Promise<ElkNode> {
      return elk.layout(graph);
    },
    terminate() {
      elk.terminateWorker();
    },
  };
}