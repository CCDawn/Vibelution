import { describe, expect, it, vi } from "vitest";

import { createChatAgentArchiveQueue } from "./useChatAgentArchiveQueue";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((nextResolve, nextReject) => {
    resolve = nextResolve;
    reject = nextReject;
  });
  return { promise, reject, resolve };
}

describe("createChatAgentArchiveQueue", () => {
  it("retires every click immediately while executing archive requests in FIFO order", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const optimistic: string[] = [];
    const executed: string[] = [];
    const pendingSnapshots: string[][] = [];
    const queue = createChatAgentArchiveQueue({
      onOptimisticArchive: (agentId) => {
        optimistic.push(agentId);
        return { agentId };
      },
      executeArchive: (agentId) => {
        executed.push(agentId);
        return agentId === "agent-a" ? first.promise : second.promise;
      },
      onArchiveSuccess: vi.fn(),
      onArchiveFailure: vi.fn(),
      onQueueDrained: vi.fn(),
      onPendingAgentIdsChanged: (ids) => pendingSnapshots.push([...ids]),
    });

    expect(queue.enqueue("agent-a")).toBe(true);
    expect(queue.enqueue("agent-b")).toBe(true);
    expect(optimistic).toEqual(["agent-a", "agent-b"]);
    expect(executed).toEqual(["agent-a"]);
    expect(queue.pendingAgentIds()).toEqual(new Set(["agent-a", "agent-b"]));

    first.resolve("archived-a");
    await Promise.resolve();
    await Promise.resolve();
    expect(executed).toEqual(["agent-a", "agent-b"]);

    second.resolve("archived-b");
    await queue.whenIdle();
    expect(queue.pendingAgentIds()).toEqual(new Set());
    expect(pendingSnapshots).toContainEqual(["agent-a", "agent-b"]);
  });

  it("reports only the failed item and continues with later queued archives", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const success = vi.fn();
    const failure = vi.fn();
    const drained = vi.fn();
    const queue = createChatAgentArchiveQueue({
      onOptimisticArchive: (agentId) => ({ optimisticAgentId: agentId }),
      executeArchive: (agentId) => agentId === "agent-a" ? first.promise : second.promise,
      onArchiveSuccess: success,
      onArchiveFailure: failure,
      onQueueDrained: drained,
      onPendingAgentIdsChanged: vi.fn(),
    });

    queue.enqueue("agent-a");
    queue.enqueue("agent-b");
    first.reject(new Error("archive A failed"));
    await Promise.resolve();
    await Promise.resolve();
    second.resolve("archived-b");
    await queue.whenIdle();

    expect(failure).toHaveBeenCalledTimes(1);
    expect(failure).toHaveBeenCalledWith(
      "agent-a",
      expect.any(Error),
      { optimisticAgentId: "agent-a" },
    );
    expect(success).toHaveBeenCalledTimes(1);
    expect(success).toHaveBeenCalledWith(
      "agent-b",
      "archived-b",
      { optimisticAgentId: "agent-b" },
    );
    expect(drained).toHaveBeenCalledTimes(1);
  });

  it("deduplicates the same Agent while allowing another Agent to queue", async () => {
    const request = deferred<string>();
    const queue = createChatAgentArchiveQueue({
      onOptimisticArchive: (agentId) => agentId,
      executeArchive: () => request.promise,
      onArchiveSuccess: vi.fn(),
      onArchiveFailure: vi.fn(),
      onQueueDrained: vi.fn(),
      onPendingAgentIdsChanged: vi.fn(),
    });

    expect(queue.enqueue(" agent-a ")).toBe(true);
    expect(queue.enqueue("agent-a")).toBe(false);
    expect(queue.enqueue("")).toBe(false);
    request.resolve("archived-a");
    await queue.whenIdle();
  });

  it("keeps ownership when another archive arrives during authoritative reconciliation", async () => {
    const reconciliation = deferred<void>();
    const executed: string[] = [];
    let reconciliationCount = 0;
    const queue = createChatAgentArchiveQueue({
      onOptimisticArchive: (agentId) => agentId,
      executeArchive: async (agentId) => {
        executed.push(agentId);
        return agentId;
      },
      onArchiveSuccess: vi.fn(),
      onArchiveFailure: vi.fn(),
      onQueueDrained: () => {
        reconciliationCount += 1;
        return reconciliationCount === 1 ? reconciliation.promise : Promise.resolve();
      },
      onPendingAgentIdsChanged: vi.fn(),
    });

    queue.enqueue("agent-a");
    await Promise.resolve();
    await Promise.resolve();
    expect(reconciliationCount).toBe(1);

    expect(queue.enqueue("agent-b")).toBe(true);
    expect(executed).toEqual(["agent-a"]);
    reconciliation.resolve();
    await queue.whenIdle();

    expect(executed).toEqual(["agent-a", "agent-b"]);
    expect(reconciliationCount).toBe(2);
  });
});
