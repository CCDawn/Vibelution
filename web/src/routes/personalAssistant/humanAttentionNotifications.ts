import type { PersonalAssistantOverview } from "../../api/types/personalAssistant";

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

export type HumanAttentionKind = "knowledge_review" | "anomaly";
export type HumanAttentionSeverity = "critical" | "high" | "medium";
export type HumanAttentionDelivery = "assistant_window" | "system_notification" | "attention_fallback";

export type HumanAttentionNotificationPayload = {
  id: string;
  kind: HumanAttentionKind;
  severity: HumanAttentionSeverity;
  title: string;
  body?: string;
  targetUrl?: string;
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
const HUMAN_ATTENTION_KINDS = new Set<string>(["knowledge_review", "anomaly"]);
const SEVERITIES = new Set<string>(["critical", "high", "medium"]);
const MAX_TITLE_LENGTH = 120;
const MAX_BODY_LENGTH = 400;
const MAX_TARGET_LENGTH = 500;
const TARGET_PATTERN = /^\/(?!\/)[A-Za-z0-9\-._~!$&'()*+,;=:@/?%]*$/;

const NOTIFIED_STORAGE_KEY = "vibelution.human-attention.notified.v1";
const MAX_NOTIFIED_IDS = 400;

/** Default workbench deep links for the two human-attention kinds. */
export const HUMAN_ATTENTION_DEFAULT_TARGETS: Record<HumanAttentionKind, string> = {
  knowledge_review: "/memory/knowledge",
  anomaly: "/teams?researchView=workflow",
};

export const HUMAN_ATTENTION_FALLBACK_TITLES: Record<HumanAttentionKind, string> = {
  knowledge_review: "知识待复核",
  anomaly: "研究流程异常待处理",
};

function normalizeText(value: unknown): string {
  return String(value ?? "").replace(/\s+/g, " ").trim();
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
  return {
    id,
    kind: row.kind,
    severity: normalizeHumanAttentionSeverity(row.severity),
    title,
    ...(body ? { body } : {}),
    ...(targetUrl ? { targetUrl } : {}),
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
  const source = raw as { id?: unknown; kind?: unknown; severity?: unknown; title?: unknown; body?: unknown; targetUrl?: unknown };
  const id = normalizeText(source.id);
  if (!ATTENTION_ID_PATTERN.test(id)) {
    return null;
  }
  if (isHumanAttentionKind(source.kind)) {
    const title = normalizeText(source.title).slice(0, MAX_TITLE_LENGTH) || HUMAN_ATTENTION_FALLBACK_TITLES[source.kind];
    const body = normalizeText(source.body).slice(0, MAX_BODY_LENGTH);
    const targetUrl = sanitizeHumanAttentionTargetUrl(source.targetUrl);
    return {
      type: "delivered",
      payload: {
        id,
        kind: source.kind,
        severity: normalizeHumanAttentionSeverity(source.severity),
        title,
        ...(body ? { body } : {}),
        ...(targetUrl ? { targetUrl } : {}),
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

/**
 * Emit notifications for every unseen human-attention row. Ids are marked
 * before the async bridge call (at-most-once per id per day). A missing
 * bridge skips silently and marks nothing.
 */
export function emitNewHumanAttentionNotifications(input: {
  rows: readonly PersonalAssistantAttentionRow[];
  bridge: HumanAttentionBridge | undefined;
  ledger: HumanAttentionLedger;
}): HumanAttentionNotificationPayload[] {
  const notify = input.bridge?.notifyHumanAttention;
  if (typeof notify !== "function") {
    return [];
  }
  const emitted: HumanAttentionNotificationPayload[] = [];
  for (const row of input.rows ?? []) {
    const payload = buildHumanAttentionNotificationPayload(row);
    if (!payload || input.ledger.has(payload.id)) {
      continue;
    }
    input.ledger.add(payload.id);
    emitted.push(payload);
    void Promise.resolve(notify(payload)).catch(() => undefined);
  }
  return emitted;
}
