/** @vitest-environment happy-dom */
import { afterEach, expect, it, vi } from "vitest";
import { createWorkflowLayoutEngine } from "./workflowElkClient";

const fixture = vi.hoisted(() => ({
  handshake: vi.fn(), layout: vi.fn(), terminate: vi.fn(), workers: [] as EventTarget[],
}));
vi.mock("elkjs/lib/elk-api", () => ({ default: class {
  constructor({ workerFactory }: { workerFactory: () => EventTarget }) { workerFactory(); }
  knownLayoutAlgorithms = fixture.handshake;
  layout = fixture.layout;
  terminateWorker = fixture.terminate;
} }));
vi.mock("elkjs/lib/elk-worker.min.js?worker", () => ({ default: class extends EventTarget {
  constructor() { super(); fixture.workers.push(this); }
} }));
afterEach(() => { fixture.workers.length = 0; vi.clearAllMocks(); });

it("waits for an actual ELK reply rather than Worker construction", async () => {
  let finish!: () => void;
  fixture.handshake.mockReturnValue(new Promise<void>((resolve) => { finish = resolve; }));
  const engine = createWorkflowLayoutEngine();
  let ready = false;
  void engine.ready.then(() => { ready = true; });
  await Promise.resolve();
  expect(ready).toBe(false);
  expect(fixture.layout).not.toHaveBeenCalled();
  finish(); await engine.ready;
  expect(ready).toBe(true);
  engine.terminate();
  expect(fixture.terminate).toHaveBeenCalledOnce();
});

it("reports Worker script failures through the readiness promise", async () => {
  fixture.handshake.mockReturnValue(new Promise(() => {}));
  const engine = createWorkflowLayoutEngine();
  const failure = expect(engine.ready).rejects.toThrow("worker download failed");
  fixture.workers[0].dispatchEvent(new ErrorEvent("error", { message: "worker download failed" }));
  await failure;
  expect(fixture.layout).not.toHaveBeenCalled();
  engine.terminate();
});
