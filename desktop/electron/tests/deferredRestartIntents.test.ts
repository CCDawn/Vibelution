import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { describe, expect, it, vi } from "vitest";

import {
  DEFERRED_RESTART_INTENT_MAX_AGE_MS,
  fulfillDeferredRestartIntentOnce,
  listDeferredRestartIntents,
  supersedePendingDeferredRestartIntents,
  type DeferredRestartIntent
} from "../src/lifecycle/deferredRestartIntents.js";

const NOW_MS = Date.parse("2026-09-16T02:00:00.000Z");

function makeWorkspace(): { root: string; runtimeManagerDir: string; intentsDir: string } {
  const root = mkdtempSync(join(tmpdir(), "vibelution-deferred-restart-"));
  const runtimeManagerDir = join(root, ".runtime", "runtime-manager");
  const intentsDir = join(runtimeManagerDir, "restart-intents");
  mkdirSync(intentsDir, { recursive: true });
  return { root, runtimeManagerDir, intentsDir };
}

function intentPayload(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  const createdAt = new Date(NOW_MS - 60_000).toISOString();
  return {
    intentId: "intent_20260916T015900Z_aaaaaaaa",
    target: "workbench_restart",
    reason: "1 active work item(s) block lifecycle commands.",
    requestedBy: "electron_main",
    sourceCommandId: "cmd-1",
    status: "pending",
    createdAt,
    updatedAt: createdAt,
    attempts: 0,
    failureCount: 0,
    lastError: "",
    nextAllowedAt: "",
    payload: { action: "restart_workbench" },
    ...overrides
  };
}

function writeIntent(intentsDir: string, payload: Record<string, unknown>): string {
  const path = join(intentsDir, `${String(payload.intentId)}.json`);
  writeFileSync(path, JSON.stringify(payload, null, 2), "utf8");
  return path;
}

function readIntent(intentsDir: string, intentId: string): DeferredRestartIntent {
  return JSON.parse(readFileSync(join(intentsDir, `${intentId}.json`), "utf8")) as DeferredRestartIntent;
}

describe("fulfillDeferredRestartIntentOnce", () => {
  it("does nothing when no intents are queued", async () => {
    const { root, runtimeManagerDir } = makeWorkspace();
    try {
      const submitRestart = vi.fn();
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "none" });
      expect(submitRestart).not.toHaveBeenCalled();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("expires intents older than the fulfilment window without restarting", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      const createdAt = new Date(NOW_MS - DEFERRED_RESTART_INTENT_MAX_AGE_MS - 60_000).toISOString();
      writeIntent(intentsDir, intentPayload({ intentId: "intent_expired", createdAt, updatedAt: createdAt }));
      const submitRestart = vi.fn();
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "expired", intentIds: ["intent_expired"] });
      expect(submitRestart).not.toHaveBeenCalled();
      expect(readIntent(intentsDir, "intent_expired").status).toBe("expired");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("keeps the intent pending while active work still blocks", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload());
      const submitRestart = vi.fn();
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [{ kind: "chat_turn", runId: "run-1" }],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "blocked", activeWorkCount: 1 });
      expect(submitRestart).not.toHaveBeenCalled();
      expect(readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa").status).toBe("pending");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("restarts through the injected submit and settles the oldest intent", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload());
      writeIntent(
        intentsDir,
        intentPayload({ intentId: "intent_20260916T015910Z_bbbbbbbb", sourceCommandId: "cmd-2" })
      );
      const submitRestart = vi.fn().mockResolvedValue({
        accepted: true,
        operation: "restart",
        commandId: "cmd_deferred"
      });
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "fulfilled", intentId: "intent_20260916T015900Z_aaaaaaaa" });
      expect(submitRestart).toHaveBeenCalledTimes(1);
      const settled = readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa");
      expect(settled).toMatchObject({
        status: "completed",
        attempts: 1,
        claimedBy: "electron_main"
      });
      expect(readIntent(intentsDir, "intent_20260916T015910Z_bbbbbbbb").status).toBe("pending");
      expect(listDeferredRestartIntents(runtimeManagerDir)).toHaveLength(2);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("puts the intent back to pending when the restart raced back into the guard", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload());
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart: async () => ({ accepted: true, code: "restart_queued", message: "still blocked" }),
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "requeued", intentId: "intent_20260916T015900Z_aaaaaaaa" });
      const settled = readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa");
      expect(settled.status).toBe("pending");
      expect(settled.attempts).toBe(1);
      expect(String(settled.message || "")).toContain("queued");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails the intent when the restart command throws", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload());
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart: async () => {
          throw new Error("launcher backend is not available");
        },
        now: () => NOW_MS
      });
      expect(outcome).toEqual({
        status: "failed",
        intentId: "intent_20260916T015900Z_aaaaaaaa",
        message: "launcher backend is not available"
      });
      const settled = readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa");
      expect(settled.status).toBe("failed");
      expect(settled.attempts).toBe(1);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("fails unsupported intent actions without restarting", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload({ payload: { action: "reopen_after_close" } }));
      const submitRestart = vi.fn();
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toMatchObject({ status: "failed", intentId: "intent_20260916T015900Z_aaaaaaaa" });
      expect(submitRestart).not.toHaveBeenCalled();
      expect(readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa").status).toBe("failed");
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });

  it("ignores intents that target other supervisors", async () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload({ target: "self_evolution_run", payload: { action: "restart_self_evolution" } }));
      const submitRestart = vi.fn();
      const outcome = await fulfillDeferredRestartIntentOnce({
        workspaceRoot: root,
        runtimeManagerDir,
        listActiveWork: () => [],
        submitRestart,
        now: () => NOW_MS
      });
      expect(outcome).toEqual({ status: "none" });
      expect(submitRestart).not.toHaveBeenCalled();
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});

describe("supersedePendingDeferredRestartIntents", () => {
  it("supersedes only pending restart intents", () => {
    const { root, runtimeManagerDir, intentsDir } = makeWorkspace();
    try {
      writeIntent(intentsDir, intentPayload());
      writeIntent(intentsDir, intentPayload({ intentId: "intent_claimed", status: "claimed" }));
      writeIntent(intentsDir, intentPayload({ intentId: "intent_done", status: "completed" }));
      writeIntent(intentsDir, intentPayload({ intentId: "intent_foreign", target: "other_target" }));
      const superseded = supersedePendingDeferredRestartIntents({
        workspaceRoot: root,
        runtimeManagerDir,
        reason: "Superseded by accepted restart command.",
        now: () => NOW_MS
      });
      expect(superseded).toEqual(["intent_20260916T015900Z_aaaaaaaa"]);
      expect(readIntent(intentsDir, "intent_20260916T015900Z_aaaaaaaa").status).toBe("superseded");
      expect(readIntent(intentsDir, "intent_claimed").status).toBe("claimed");
      expect(readIntent(intentsDir, "intent_done").status).toBe("completed");
      expect(readIntent(intentsDir, "intent_foreign").status).toBe("pending");
      expect(readdirSync(intentsDir).filter((name) => name.endsWith(".tmp"))).toEqual([]);
    } finally {
      rmSync(root, { recursive: true, force: true });
    }
  });
});
