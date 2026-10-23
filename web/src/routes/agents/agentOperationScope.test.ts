import { expect, it, vi } from "vitest";
import { AgentOperationInProgressError, createAgentOperationScope } from "./agentOperationScope";

it("keeps independent Agent operations available and rejects overlap atomically", () => {
  const notify = vi.fn();
  const scope = createAgentOperationScope(notify);
  const releaseA = scope.begin(["a"]);
  expect(() => scope.begin(["b", "a"])).toThrow(AgentOperationInProgressError);
  expect(scope.isPending("b")).toBe(false);
  const releaseB = scope.begin(["b"]);
  releaseA();
  expect(notify.mock.calls.at(-1)?.[0]).toEqual(new Set(["b"]));
  releaseB();
  expect(notify.mock.calls.at(-1)?.[0]).toEqual(new Set());
});

it("an old release cannot unlock a later operation on the same Agent", () => {
  const scope = createAgentOperationScope(() => {});
  const releaseOld = scope.begin(["a"]);
  releaseOld();
  const releaseNew = scope.begin(["a"]);
  releaseOld();
  expect(scope.isPending("a")).toBe(true);
  releaseNew();
  expect(scope.isPending("a")).toBe(false);
});
