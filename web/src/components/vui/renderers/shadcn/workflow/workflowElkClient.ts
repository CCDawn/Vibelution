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
  /** Resolves only after the Worker has loaded and can answer ELK requests. */
  ready: Promise<void>;
  layout(graph: ElkNode): Promise<ElkNode>;
  /** Release worker/global resources; engine is unusable afterwards. */
  terminate(): void;
};

export function createWorkflowLayoutEngine(): WorkflowLayoutEngine {
  const worker = new ElkWorker();
  const elk = new ELK({
    workerFactory: () => worker,
  });
  const ready = new Promise<void>((resolve, reject) => {
    const onError = (event: ErrorEvent) => {
      worker.removeEventListener("error", onError);
      reject(new Error(event.message || "layout Worker could not load"));
    };
    worker.addEventListener("error", onError);
    // ELK's public query API is a real Worker handshake, not a fixed delay.
    elk.knownLayoutAlgorithms().then(() => {
      worker.removeEventListener("error", onError);
      resolve();
    }, (error) => {
      worker.removeEventListener("error", onError);
      reject(error);
    });
  });
  return {
    ready,
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
