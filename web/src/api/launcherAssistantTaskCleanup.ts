import { launcherAssistantInvoke, type LauncherTaskCleanupTarget } from "./launcherAssistant";

export type { LauncherTaskCleanupTarget } from "./launcherAssistant";
export type LauncherTaskCleanupScope = { agentId: string; directSessionId: string; targets: LauncherTaskCleanupTarget[] };
export type LauncherTaskCleanupRetained = { kind: string; reason: string };
export type LauncherTaskCleanupPreview = {
  schemaVersion: 1; fingerprint: string; estimatedBytes: number;
  items: { key: string; title: string; status: "ready" | "blocked"; estimatedBytes: number;
    resources: { kind: string; count: number; bytes: number }[]; retained: LauncherTaskCleanupRetained[]; reason?: string }[];
};
export type LauncherTaskCleanupResult = {
  schemaVersion: 1; releasedBytes: number;
  storageDeltaBytes?: number;
  items: { key: string; status: "deleted" | "partial" | "blocked"; releasedBytes: number;
    retained: LauncherTaskCleanupRetained[]; failures: { code: string; message: string }[] }[];
};

const record = (value: unknown): value is Record<string, unknown> => Boolean(value) && typeof value === "object" && !Array.isArray(value);
const count = (value: unknown): value is number => Number.isSafeInteger(value) && (value as number) >= 0;
const text = (value: unknown, max = 2000): value is string => typeof value === "string" && value.length <= max;
const retained = (value: unknown): boolean => Array.isArray(value) && value.length <= 256
  && value.every(item => record(item) && text(item.kind, 100) && text(item.reason));
const invalid = () => new Error("Launcher 任务清理结果不可用，请重试。");
const targetKey = (target: LauncherTaskCleanupTarget) => JSON.stringify([target.kind, target.projectId,
  target.kind === "dispatch" ? target.dispatchId : target.originAction, target.kind === "team_run" ? target.requestId : null]);
const scopeKey = (scope: LauncherTaskCleanupScope) => JSON.stringify([scope.agentId, scope.directSessionId, scope.targets.map(target =>
  target.kind === "dispatch" ? [target.kind, target.projectId, target.dispatchId, target.localOnly === true]
    : [target.kind, target.projectId, target.requestId, target.originAction, target.teamId, target.flowId, target.runId, target.localOnly === true])]);
const matchingItems = (items: { key: string }[], targets: LauncherTaskCleanupTarget[]) => items.length === targets.length
  && new Set(items.map(item => item.key)).size === targets.length
  && targets.every(target => items.some(item => item.key === targetKey(target)));

function previewValue(result: unknown, targets: LauncherTaskCleanupTarget[]): LauncherTaskCleanupPreview {
  if (!record(result) || result.schemaVersion !== 1 || !text(result.fingerprint, 256) || !result.fingerprint
    || !count(result.estimatedBytes) || !Array.isArray(result.items) || result.items.length > 32
    || !result.items.every(item => record(item) && text(item.key, 1000) && text(item.title, 200)
      && ["ready", "blocked"].includes(String(item.status)) && count(item.estimatedBytes) && retained(item.retained)
      && (item.reason === undefined || text(item.reason)) && Array.isArray(item.resources) && item.resources.length <= 256
      && item.resources.every(resource => record(resource) && text(resource.kind, 100) && count(resource.count) && count(resource.bytes)))) throw invalid();
  const preview = result as LauncherTaskCleanupPreview;
  if (!matchingItems(preview.items, targets)) throw invalid();
  return preview;
}

function resultValue(result: unknown, targets: LauncherTaskCleanupTarget[]): LauncherTaskCleanupResult {
  if (!record(result) || result.schemaVersion !== 1 || !count(result.releasedBytes) || result.storageDeltaBytes !== undefined && !Number.isSafeInteger(result.storageDeltaBytes) || !Array.isArray(result.items) || result.items.length > 32
    || !result.items.every(item => record(item) && text(item.key, 1000)
      && ["deleted", "partial", "blocked"].includes(String(item.status)) && count(item.releasedBytes) && retained(item.retained)
      && Array.isArray(item.failures) && item.failures.length <= 256
      && item.failures.every(failure => record(failure) && text(failure.code, 100) && text(failure.message)))) throw invalid();
  const outcome = result as LauncherTaskCleanupResult;
  if (!matchingItems(outcome.items, targets)) throw invalid();
  return outcome;
}

type CleanupPlan = { identity: string; expiresAt: number; batches: { targets: LauncherTaskCleanupTarget[]; fingerprint: string }[] };
// A bounded, one-use transport plan, never a task store or durable deletion queue.
const plans = new Map<string, CleanupPlan>();
const PREVIEW_TTL = 5 * 60_000;

function expirePlans() {
  for (const [key, plan] of plans) if (plan.expiresAt <= Date.now()) plans.delete(key);
}

/** Host-owned previews, in batches of at most 32 without dropping any aliases. */
export async function previewLauncherTaskCleanup(scope: LauncherTaskCleanupScope, options: { signal?: AbortSignal } = {}): Promise<LauncherTaskCleanupPreview> {
  options.signal?.throwIfAborted();
  if (!scope.agentId || !scope.directSessionId || !scope.targets.length) throw invalid();
  if (scope.targets.length > 512) throw new Error("当前清理范围超过 512 条关联，请减少范围或逐项删除。");
  if (new Set(scope.targets.map(targetKey)).size !== scope.targets.length) throw invalid();
  // Snapshot references so a caller mutation cannot change an approved scope.
  const identity = scopeKey(scope), targets = structuredClone(scope.targets);
  const { agentId, directSessionId } = scope;
  const batches: CleanupPlan["batches"] = [], items: LauncherTaskCleanupPreview["items"] = [];
  let estimatedBytes = 0;
  for (let offset = 0; offset < targets.length; offset += 32) {
    options.signal?.throwIfAborted();
    const batch = targets.slice(offset, offset + 32);
    const preview = previewValue(await launcherAssistantInvoke({ operation: "previewTaskCleanup", agentId, directSessionId, targets: batch }), batch);
    options.signal?.throwIfAborted();
    batches.push({ targets: batch, fingerprint: preview.fingerprint }); items.push(...preview.items);
    estimatedBytes += preview.estimatedBytes;
    if (!count(estimatedBytes)) throw invalid();
  }
  expirePlans();
  while (plans.size >= 16) plans.delete(plans.keys().next().value!);
  const fingerprint = Array.from(crypto.getRandomValues(new Uint8Array(32)), byte => byte.toString(16).padStart(2, "0")).join("");
  plans.set(fingerprint, { identity, expiresAt: Date.now() + PREVIEW_TTL, batches });
  return { schemaVersion: 1, fingerprint, estimatedBytes, items };
}

/** Each native fingerprint is used once and only for its identity-bound preview. */
export async function executeLauncherTaskCleanup(scope: LauncherTaskCleanupScope, fingerprint: string,
  options: { signal?: AbortSignal } = {}): Promise<LauncherTaskCleanupResult> {
  options.signal?.throwIfAborted(); expirePlans();
  const plan = plans.get(fingerprint);
  if (!plan || plan.identity !== scopeKey(scope)) throw new Error("清理范围已失效，请重试。");
  plans.delete(fingerprint);
  const { agentId, directSessionId } = scope;
  const items: LauncherTaskCleanupResult["items"] = [];
  let releasedBytes = 0, storageDeltaBytes = 0;
  for (const batch of plan.batches) {
    options.signal?.throwIfAborted();
    try {
      const result = resultValue(await launcherAssistantInvoke({ operation: "executeTaskCleanup", agentId, directSessionId,
        targets: batch.targets, fingerprint: batch.fingerprint }), batch.targets);
      options.signal?.throwIfAborted();
      const nextDelta = storageDeltaBytes + (result.storageDeltaBytes ?? result.releasedBytes);
      if (!Number.isSafeInteger(nextDelta)) throw invalid();
      items.push(...result.items); storageDeltaBytes = nextDelta; releasedBytes = Math.max(0, nextDelta);
    } catch (error) {
      options.signal?.throwIfAborted();
      const message = `此批清理未获确认，部分记录可能已删除，请重试。${String(error instanceof Error ? error.message : error).slice(0, 600)}`;
      items.push(...batch.targets.map(target => ({ key: targetKey(target), status: "blocked" as const, releasedBytes: 0,
        retained: [], failures: [{ code: "cleanup_batch_unconfirmed", message }] })));
    }
  }
  return { schemaVersion: 1, releasedBytes, storageDeltaBytes, items };
}

/** One operator action, with each host-owned plan executed before the next batch. */
export async function cleanupLauncherTasks(scope: LauncherTaskCleanupScope,
  options: { signal?: AbortSignal } = {}): Promise<LauncherTaskCleanupResult> {
  options.signal?.throwIfAborted();
  if (!scope.agentId || !scope.directSessionId || !scope.targets.length
    || new Set(scope.targets.map(targetKey)).size !== scope.targets.length) throw invalid();
  const targets = structuredClone(scope.targets);
  const items: LauncherTaskCleanupResult["items"] = [];
  let storageDeltaBytes = 0;
  // Bound each native RPC even when several sources are slow. Plans remain
  // short-lived and execution still rechecks native ownership and revision.
  for (let offset = 0; offset < targets.length; offset += 2) {
    options.signal?.throwIfAborted();
    const batch = { agentId: scope.agentId, directSessionId: scope.directSessionId, targets: targets.slice(offset, offset + 2) };
    try {
      const preview = await previewLauncherTaskCleanup(batch, options);
      options.signal?.throwIfAborted();
      const blocked = new Map(preview.items.filter(item => item.status === "blocked").map(item => [item.key, item]));
      const result = preview.items.some(item => item.status === "ready")
        ? await executeLauncherTaskCleanup(batch, preview.fingerprint, options)
        : { schemaVersion: 1 as const, releasedBytes: 0, storageDeltaBytes: 0, items: [] };
      options.signal?.throwIfAborted();
      const batchItems = batch.targets.map(target => {
        const key = targetKey(target), unavailable = blocked.get(key);
        if (unavailable) return { key, status: "blocked" as const, releasedBytes: 0, retained: unavailable.retained,
          failures: [{ code: "cleanup_source_blocked", message: unavailable.reason || "任务来源或终态暂未确认，请稍后重试。" }] };
        const item = result.items.find(row => row.key === key);
        if (!item) throw invalid();
        return item;
      });
      const nextDelta = storageDeltaBytes + (result.storageDeltaBytes ?? result.releasedBytes);
      if (!Number.isSafeInteger(nextDelta)) throw invalid();
      storageDeltaBytes = nextDelta;
      items.push(...batchItems);
    } catch (error) {
      options.signal?.throwIfAborted();
      const message = `此批清理未获确认，请重试。${String(error instanceof Error ? error.message : error).slice(0, 600)}`;
      items.push(...batch.targets.map(target => ({ key: targetKey(target), status: "blocked" as const, releasedBytes: 0,
        retained: [], failures: [{ code: "cleanup_batch_unconfirmed", message }] })));
    }
  }
  return { schemaVersion: 1, releasedBytes: Math.max(0, storageDeltaBytes), storageDeltaBytes, items };
}
