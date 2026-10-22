import type { PersonalAssistantOverview } from "../../api/types/personalAssistant";
import { reportHumanAttentionDeliveryFailure } from "../../api/personalAttentionFailureReport";

/**
 * Dual-channel human-attention notifications (web layer).
 * The floating assistant window receives in-window notice cards; when it is
 * closed the Electron main process shows a Windows system notification and
 * broadcasts the "opened" click back. This module owns the shared web-side
 * contract: bridge discovery, payload building, day-scoped dedup and event
 * parsing. No new backend path is introduced — attention rows come from the
 * existing personal-assistant overview polling.
 */

export type PersonalAssistantAttentionRow = PersonalAssistantOverview["attention"][number];

export type HumanAttentionKind =
  | "knowledge_review"
  | "anomaly"
  | "affair_reminder"
  | "human_gate"
  | "dispatch_receipt"
  | "run_completed"
  | "session_completed"
  | "assistant_digest";
/** info 只用于完成类事件（好消息），不占用停靠/异常的 critical/high 语义。 */
export type HumanAttentionSeverity = "critical" | "high" | "medium" | "info";
export type HumanAttentionDelivery = "assistant_window" | "system_notification" | "attention_fallback";

/** Server-labeled approve affordance (human_gate rows render these inline). */
export type HumanAttentionNotificationAction = {
  label: string;
  decision: string;
};

/** Research human-gate routing facts (used to locate the resolve offer). */
export type HumanAttentionNotificationMeta = {
  teamId?: string;
  runId?: string;
  nodeId?: string;
  taskId?: string;
  decisions?: string[];
};

export type HumanAttentionNotificationPayload = {
  id: string;
  kind: HumanAttentionKind;
  severity: HumanAttentionSeverity;
  title: string;
  body?: string;
  targetUrl?: string;
  actions?: HumanAttentionNotificationAction[];
  meta?: HumanAttentionNotificationMeta;
};

export type HumanAttentionOpenedPayload = {
  id: string;
  targetUrl?: string;
};

/** Full payloads are window deliveries (notice cards); bare ids are opened clicks. */
export type HumanAttentionEvent =
  | { type: "delivered"; payload: HumanAttentionNotificationPayload }
  | { type: "opened"; payload: HumanAttentionOpenedPayload };

export type HumanAttentionBridge = {
  notifyHumanAttention?: (payload: HumanAttentionNotificationPayload) => Promise<unknown>;
  onHumanAttentionOpened?: (listener: (payload: unknown) => void) => () => void;
};

const ATTENTION_ID_PATTERN = /^[A-Za-z0-9._:-]{1,128}$/;
/**
 * Single source of truth for human-attention kinds. The Electron shell keeps
 * its own copy (`desktop/electron/src/notifications/humanAttentionNotifications.ts`);
 * both sides must accept the same set and `desktop/electron/tests/humanAttentionNotifications.test.ts`
 * asserts they stay in sync.
 */
export const HUMAN_ATTENTION_KINDS = new Set<string>([
  "knowledge_review",
  "anomaly",
  "affair_reminder",
  "human_gate",
  "dispatch_receipt",
  "run_completed",
  "session_completed",
  "assistant_digest",
]);
const SEVERITIES = new Set<string>(["critical", "high", "medium", "info"]);
const MAX_TITLE_LENGTH = 120;
const MAX_BODY_LENGTH = 400;
const MAX_TARGET_LENGTH = 500;
const MAX_ACTIONS = 4;
const MAX_ACTION_LABEL_LENGTH = 40;
const MAX_ACTION_DECISION_LENGTH = 24;
const MAX_META_VALUE_LENGTH = 128;
const TARGET_PATTERN = /^\/(?!\/)[A-Za-z0-9\-._~!$&'()*+,;=:@/?%]*$/;

const NOTIFIED_STORAGE_KEY = "vibelution.human-attention.notified.v1";
const MAX_NOTIFIED_IDS = 400;

/** Default workbench deep links for the human-attention kinds. */
export const HUMAN_ATTENTION_DEFAULT_TARGETS: Record<HumanAttentionKind, string> = {
  knowledge_review: "/memory/knowledge",
  anomaly: "/teams?researchView=workflow",
  affair_reminder: "/personal-assistant",
  human_gate: "/teams?researchView=workflow",
  // 完成类事件的默认深链与后端 targetUrl 缺省兜底保持同一落点：
  // 派遣 tab / 科研工作流 / 会话页。
  dispatch_receipt: "/personal-assistant?panel=dispatches",
  run_completed: "/teams?researchView=workflow",
  session_completed: "/chat",
  // PA 心跳巡检的定时摘要卡：点击落回助理面板。
  assistant_digest: "/personal-assistant",
};

export const HUMAN_ATTENTION_FALLBACK_TITLES: Record<HumanAttentionKind, string> = {
  knowledge_review: "知识待复核",
  anomaly: "研究流程异常待处理",
  affair_reminder: "事务提醒待处理",
  human_gate: "研究流程等待人工审批",
  dispatch_receipt: "派遣回执已到达",
  run_completed: "研究运行已完成",
  session_completed: "会话已完成",
  assistant_digest: "助理派遣摘要",
};

function normalizeText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
}

/** Keep only well-formed server actions (label + decision); bounded and deduped by decision. */
export function normalizeHumanAttentionActions(raw: unknown): HumanAttentionNotificationAction[] | undefined {
  if (!Array.isArray(raw)) {
    return undefined;
  }
  const actions: HumanAttentionNotificationAction[] = [];
  const seenDecisions = new Set<string>();
  for (const entry of raw.slice(0, MAX_ACTIONS)) {
    if (typeof entry !== "object" || entry === null) {
      continue;
    }
    const source = entry as { label?: unknown; decision?: unknown };
    if (typeof source.label !== "string" || typeof source.decision !== "string") {
      continue;
    }
    const label = source.label.replace(/\s+/g, " ").trim().slice(0, MAX_ACTION_LABEL_LENGTH);
    const decision = source.decision.replace(/\s+/g, " ").trim().slice(0, MAX_ACTION_DECISION_LENGTH);
    if (!label || !decision || seenDecisions.has(decision)) {
      continue;
    }
    seenDecisions.add(decision);
    actions.push({ label, decision });
  }
  return actions.length > 0 ? actions : undefined;
}

/** Keep the known human-gate routing keys; every value is a trimmed non-empty string. */
export function normalizeHumanAttentionMeta(raw: unknown): HumanAttentionNotificationMeta | undefined {
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    return undefined;
  }
  const source = raw as Record<string, unknown>;
  const value = (key: string): string | undefined => {
    if (typeof source[key] !== "string") {
      return undefined;
    }
    const text = (source[key] as string).replace(/\s+/g, " ").trim().slice(0, MAX_META_VALUE_LENGTH);
    return text || undefined;
  };
  const decisions = Array.isArray(source.decisions)
    ? source.decisions
      .map(decision => normalizeText(decision).slice(0, MAX_ACTION_DECISION_LENGTH))
      .filter(Boolean)
    : undefined;
  const meta: HumanAttentionNotificationMeta = {
    ...(value("teamId") ? { teamId: value("teamId") } : {}),
    ...(value("runId") ? { runId: value("runId") } : {}),
    ...(value("nodeId") ? { nodeId: value("nodeId") } : {}),
    ...(value("taskId") ? { taskId: value("taskId") } : {}),
    ...(decisions && decisions.length > 0 ? { decisions } : {}),
  };
  return Object.keys(meta).length > 0 ? meta : undefined;
}

export function isHumanAttentionKind(value: unknown): value is HumanAttentionKind {
  return typeof value === "string" && HUMAN_ATTENTION_KINDS.has(value);
}

export function normalizeHumanAttentionSeverity(value: unknown): HumanAttentionSeverity {
  return typeof value === "string" && SEVERITIES.has(value) ? (value as HumanAttentionSeverity) : "medium";
}

/** Same-site absolute path only; protocol-relative and external URLs are rejected. */
export function sanitizeHumanAttentionTargetUrl(raw: unknown): string {
  const value = normalizeText(raw);
  if (!value || value.length > MAX_TARGET_LENGTH || !TARGET_PATTERN.test(value)) {
    return "";
  }
  return value;
}

/** Bridge view over the global Electron preload exposure; undefined when absent (browser). */
export function humanAttentionBridge(globalLike: unknown = globalThis): HumanAttentionBridge | undefined {
  const bridge = (globalLike as { vibelutionLauncher?: unknown })?.vibelutionLauncher;
  if (typeof bridge !== "object" || bridge === null) {
    return undefined;
  }
  const candidate = bridge as HumanAttentionBridge;
  const notify = typeof candidate.notifyHumanAttention === "function" ? candidate.notifyHumanAttention.bind(bridge) : undefined;
  const subscribe = typeof candidate.onHumanAttentionOpened === "function" ? candidate.onHumanAttentionOpened.bind(bridge) : undefined;
  if (!notify && !subscribe) {
    return undefined;
  }
  return {
    ...(notify ? { notifyHumanAttention: notify } : {}),
    ...(subscribe ? { onHumanAttentionOpened: subscribe } : {}),
  };
}

/** Attention row → bridge payload; null for non-human-attention kinds or invalid ids. */
export function buildHumanAttentionNotificationPayload(
  row: PersonalAssistantAttentionRow | undefined,
): HumanAttentionNotificationPayload | null {
  if (!row || !isHumanAttentionKind(row.kind)) {
    return null;
  }
  const id = normalizeText(row.id);
  if (!ATTENTION_ID_PATTERN.test(id)) {
    return null;
  }
  const title = normalizeText(row.title).slice(0, MAX_TITLE_LENGTH) || HUMAN_ATTENTION_FALLBACK_TITLES[row.kind];
  const body = normalizeText(row.body).slice(0, MAX_BODY_LENGTH);
  const targetUrl = sanitizeHumanAttentionTargetUrl(row.targetUrl);
  const actions = normalizeHumanAttentionActions(row.actions);
  const meta = normalizeHumanAttentionMeta(row.meta);
  return {
    id,
    kind: row.kind,
    severity: normalizeHumanAttentionSeverity(row.severity),
    title,
    ...(body ? { body } : {}),
    ...(targetUrl ? { targetUrl } : {}),
    ...(actions ? { actions } : {}),
    ...(meta ? { meta } : {}),
  };
}

/**
 * Tolerant event parse. A payload with a valid human-attention kind is a
 * window delivery (notice card); anything else with a valid id is an opened
 * click from the shell ({ id, targetUrl? }).
 */
export function parseHumanAttentionEvent(raw: unknown): HumanAttentionEvent | null {
  if (typeof raw !== "object" || raw === null) {
    return null;
  }
  const source = raw as {
    id?: unknown;
    kind?: unknown;
    severity?: unknown;
    title?: unknown;
    body?: unknown;
    targetUrl?: unknown;
    actions?: unknown;
    meta?: unknown;
  };
  const id = normalizeText(source.id);
  if (!ATTENTION_ID_PATTERN.test(id)) {
    return null;
  }
  if (isHumanAttentionKind(source.kind)) {
    const title = normalizeText(source.title).slice(0, MAX_TITLE_LENGTH) || HUMAN_ATTENTION_FALLBACK_TITLES[source.kind];
    const body = normalizeText(source.body).slice(0, MAX_BODY_LENGTH);
    const targetUrl = sanitizeHumanAttentionTargetUrl(source.targetUrl);
    const actions = normalizeHumanAttentionActions(source.actions);
    const meta = normalizeHumanAttentionMeta(source.meta);
    return {
      type: "delivered",
      payload: {
        id,
        kind: source.kind,
        severity: normalizeHumanAttentionSeverity(source.severity),
        title,
        ...(body ? { body } : {}),
        ...(targetUrl ? { targetUrl } : {}),
        ...(actions ? { actions } : {}),
        ...(meta ? { meta } : {}),
      },
    };
  }
  const targetUrl = sanitizeHumanAttentionTargetUrl(source.targetUrl);
  return { type: "opened", payload: { id, ...(targetUrl ? { targetUrl } : {}) } };
}

export function subscribeHumanAttentionEvents(
  bridge: HumanAttentionBridge | undefined,
  onEvent: (event: HumanAttentionEvent) => void,
): () => void {
  if (typeof bridge?.onHumanAttentionOpened !== "function") {
    return () => undefined;
  }
  return bridge.onHumanAttentionOpened(raw => {
    const event = parseHumanAttentionEvent(raw);
    if (event) {
      onEvent(event);
    }
  });
}

/** Resolve the navigation target: sanitized targetUrl, else the kind default, else "". */
export function humanAttentionTargetFor(payload: { targetUrl?: unknown; kind?: unknown }): string {
  return sanitizeHumanAttentionTargetUrl(payload.targetUrl)
    || (isHumanAttentionKind(payload.kind) ? HUMAN_ATTENTION_DEFAULT_TARGETS[payload.kind] : "");
}

export function localDayKey(date: Date): string {
  const year = date.getFullYear();
  const month = `${date.getMonth() + 1}`.padStart(2, "0");
  const day = `${date.getDate()}`.padStart(2, "0");
  return `${year}-${month}-${day}`;
}

type NotifiedLedger = { day: string; ids: string[] };

function readNotifiedLedger(storage: Pick<Storage, "getItem">, day: string): string[] {
  try {
    const raw = storage.getItem(NOTIFIED_STORAGE_KEY);
    const value = raw ? (JSON.parse(raw) as Partial<NotifiedLedger> | null) : null;
    return value && value.day === day && Array.isArray(value.ids)
      ? value.ids.filter((id): id is string => typeof id === "string")
      : [];
  } catch {
    return [];
  }
}

function writeNotifiedLedger(storage: Pick<Storage, "setItem">, day: string, ids: string[]): boolean {
  try {
    storage.setItem(NOTIFIED_STORAGE_KEY, JSON.stringify({ day, ids: ids.slice(-MAX_NOTIFIED_IDS) }));
    return true;
  } catch {
    return false;
  }
}

export type HumanAttentionLedger = {
  has(id: string): boolean;
  add(id: string): void;
};

/** Day-scoped dedup ledger; survives page refreshes through localStorage. */
export function createHumanAttentionLedger(
  storage: Pick<Storage, "getItem" | "setItem"> | undefined,
  day: string,
): HumanAttentionLedger {
  let ids = storage ? readNotifiedLedger(storage, day) : [];
  const known = new Set<string>(ids);
  return {
    has(id) {
      return known.has(id);
    },
    add(id) {
      if (known.has(id)) {
        return;
      }
      known.add(id);
      ids.push(id);
      if (ids.length > MAX_NOTIFIED_IDS) {
        const evicted = ids.slice(0, ids.length - MAX_NOTIFIED_IDS);
        ids = ids.slice(ids.length - MAX_NOTIFIED_IDS);
        for (const value of evicted) {
          known.delete(value);
        }
      }
      if (storage) {
        writeNotifiedLedger(storage, day, ids);
      }
    },
  };
}

/** localStorage access that tolerates blocked storage (private mode, tests). */
export function browserHumanAttentionStorage(): Pick<Storage, "getItem" | "setItem"> | undefined {
  try {
    return typeof localStorage === "undefined" ? undefined : localStorage;
  } catch {
    return undefined;
  }
}

/** Reject reasons the shell reports as a structured result instead of a throw. */
function isInvalidPayloadDeliveryResult(result: unknown): boolean {
  return (
    typeof result === "object"
    && result !== null
    && (result as { delivered?: unknown }).delivered === "invalid_payload"
  );
}

/**
 * Emit notifications for every unseen human-attention row. Ids are marked
 * before the async bridge call (at-most-once per id per day). A missing
 * bridge skips silently and marks nothing. Because the ledger already
 * consumed the id, a rejected IPC call or an invalid_payload result is
 * reported to the personal-assistant inbox (fire-and-forget, deduped and
 * capped inside the reporter) instead of being lost — a missing bridge is
 * the plain-browser case and is never reported.
 */
export function emitNewHumanAttentionNotifications(input: {
  rows: readonly PersonalAssistantAttentionRow[];
  bridge: HumanAttentionBridge | undefined;
  ledger: HumanAttentionLedger;
  reportFailure?: (report: {
    id: string;
    kind: string;
    severity?: string;
    reason: string;
    title?: string;
  }) => void;
}): HumanAttentionNotificationPayload[] {
  const notify = input.bridge?.notifyHumanAttention;
  if (typeof notify !== "function") {
    return [];
  }
  const reportFailure = input.reportFailure ?? reportHumanAttentionDeliveryFailure;
  const safeReportFailure = (report: {
    id: string;
    kind: string;
    severity?: string;
    reason: string;
    title?: string;
  }): void => {
    try {
      reportFailure(report);
    } catch {
      // Reporting must never turn into an unhandled rejection.
    }
  };
  const emitted: HumanAttentionNotificationPayload[] = [];
  for (const row of input.rows ?? []) {
    const payload = buildHumanAttentionNotificationPayload(row);
    if (!payload || input.ledger.has(payload.id)) {
      continue;
    }
    input.ledger.add(payload.id);
    emitted.push(payload);
    void Promise.resolve(notify(payload)).then(
      (result) => {
        if (isInvalidPayloadDeliveryResult(result)) {
          safeReportFailure({
            id: payload.id,
            kind: payload.kind,
            severity: payload.severity,
            reason: "notify resolved with delivered=invalid_payload",
            title: payload.title,
          });
        }
      },
      (error: unknown) => {
        safeReportFailure({
          id: payload.id,
          kind: payload.kind,
          severity: payload.severity,
          reason: `notify rejected: ${error instanceof Error ? error.message : String(error)}`,
          title: payload.title,
        });
      },
    );
  }
  return emitted;
}
