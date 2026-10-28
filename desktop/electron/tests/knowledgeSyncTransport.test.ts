import { createHash } from "node:crypto";
import { expect, it } from "vitest";
import { parseMainControlClaim, projectMainControlResult } from "../src/assistant/mainControlTransport.js";

it("binds the incremental ID to its exact project and preview and keeps queued distinct from completion", () => {
  const projectId = "project:one", previewId = "a".repeat(64);
  const operationId = "ksync-" + createHash("sha256").update(`${projectId}:${previewId}`).digest("hex").slice(0, 40);
  const row = { deliveryId: "b".repeat(32), action: "initial_migration_queue", projectId, previewId,
    turnId: "turn-one", category: "knowledge_sync", operationId, timeoutMs: 5000 };
  const request = parseMainControlClaim({ schemaVersion: 1, request: row });
  expect(request).toEqual(row);
  expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, projectId: "project:other" } })).toThrow();
  expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, previewId: "b".repeat(64) } })).toThrow();
  expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, operationId: "initial-" + "a".repeat(40) } })).toThrow();
  const value = { schemaVersion: 1, projectId, previewId, category: "knowledge_sync", operationId,
    state: "queued", code: "queued", readyForCutover: false };
  expect(projectMainControlResult(request!, value)).toEqual(value);
  expect(projectMainControlResult(request!, { ...value, state: "completed", code: "completed" })).toMatchObject({ state: "unknown" });
});

it("binds a recovery attempt to its original sync and approved preview", () => {
  const projectId = "project:one", previewId = "a".repeat(64), originalSyncId = "ksync-" + "d".repeat(40);
  const operationId = "krec-" + createHash("sha256").update(`${projectId}:${previewId}:${originalSyncId}`).digest("hex").slice(0, 40);
  const row = { deliveryId: "b".repeat(32), action: "initial_migration_queue", projectId, previewId,
    turnId: "turn-one", category: "knowledge_recovery", operationId, originalSyncId, timeoutMs: 5000 };
  const request = parseMainControlClaim({ schemaVersion: 1, request: row });
  expect(request).toEqual(row);
  expect(() => parseMainControlClaim({ schemaVersion: 1, request: { ...row, originalSyncId: "ksync-" + "e".repeat(40) } })).toThrow();
  const base = { schemaVersion: 1, projectId, previewId, category: "knowledge_recovery", operationId, originalSyncId,
    state: "queued", code: "queued", readyForCutover: false };
  expect(projectMainControlResult(request!, base)).toEqual(base);
  expect(projectMainControlResult(request!, { ...base, originalSyncId: "ksync-" + "e".repeat(40) })).toMatchObject({ state: "unknown" });
});
