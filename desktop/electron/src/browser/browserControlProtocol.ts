/** Closed, bounded private browser protocol. Page content remains untrusted. */
export type BrowserAction = "browser_state" | "browser_open" | "browser_ensure" | "browser_select" | "browser_show" | "browser_read" | "browser_navigate" | "browser_back" | "browser_forward" | "browser_reload" | "browser_scroll" | "browser_interact";
export type BrowserMainControlRequest = { deliveryId: string } & (
  | { action: "browser_state" | "browser_show" }
  | { action: "browser_open" | "browser_ensure"; url: string }
  | { action: "browser_read" | "browser_select" | "browser_back" | "browser_forward" | "browser_reload"; pageId: string }
  | { action: "browser_navigate"; pageId: string; url: string }
  | { action: "browser_scroll"; pageId: string; direction: "up" | "down" }
  | { action: "browser_interact"; pageId: string; snapshotId: string; elementRef: string; url: string; elementName: string; operation: "click" }
  | { action: "browser_interact"; pageId: string; snapshotId: string; elementRef: string; url: string; elementName: string; operation: "fill"; value: string }
);
const actions: readonly string[] = ["browser_state", "browser_open", "browser_ensure", "browser_select", "browser_show", "browser_read", "browser_navigate", "browser_back", "browser_forward", "browser_reload", "browser_scroll", "browser_interact"];
export const browserErrorCodes: readonly string[] = ["BROWSER_URL_INVALID", "BROWSER_PAGE_LIMIT", "BROWSER_SOURCE_INVALID", "BROWSER_SOURCE_FORBIDDEN", "BROWSER_DISPOSED", "BROWSER_PAGE_NOT_FOUND", "BROWSER_NAVIGATION_FAILED", "BROWSER_SNAPSHOT_FAILED", "BROWSER_SNAPSHOT_STALE", "BROWSER_PAGE_NOT_VISIBLE", "BROWSER_TARGET_UNAVAILABLE", "BROWSER_VALUE_INVALID", "BROWSER_ACTION_FAILED", "BROWSER_ACTION_OUTCOME_UNKNOWN", "BROWSER_DIRECTION_INVALID", "BROWSER_BOUNDS_INVALID", "BROWSER_TAKEOVER_ACTIVE", "BROWSER_UNAVAILABLE"];
export const isBrowserAction = (value: unknown): value is BrowserAction => typeof value === "string" && actions.includes(value);
export function closed(value: unknown, required: string[], optional: string[] = []): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(value).length === Object.keys(descriptors).length && required.every(key => Object.hasOwn(descriptors, key))
    && Object.entries(descriptors).every(([key, d]) => [...required, ...optional].includes(key) && Object.hasOwn(d, "value") && d.enumerable);
}
function array(value: unknown, max: number): value is unknown[] {
  if (!Array.isArray(value) || Object.getPrototypeOf(value) !== Array.prototype || value.length > max) return false;
  const d = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(value).length === value.length + 1 && Array.from({ length: value.length }, (_, i) => d[String(i)]).every(x => x && Object.hasOwn(x, "value") && x.enumerable);
}
export const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/.test(v);
const wellFormed = (v: string): boolean => !/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/.test(v);
const str = (v: unknown, n: number): v is string => typeof v === "string" && v.length <= n && wellFormed(v);
export function browserUrl(v: unknown, allowEmpty = false): v is string {
  if (!str(v, 8192) || /[\x00-\x1f\x7f]/.test(v)) return false;
  if (allowEmpty && v === "") return true;
  if (!/^https?:\/\//i.test(v) || /^https?:\/\/[^/?#]*@/i.test(v)) return false;
  try { const u = new URL(v); return (u.protocol === "http:" || u.protocol === "https:") && !!u.hostname && !u.username && !u.password; } catch { return false; }
}
const ref = (v: unknown): boolean => typeof v === "string" && /^[1-9][0-9]{0,2}$/.test(v);
function bounded(value: unknown): boolean { try { return Buffer.byteLength(JSON.stringify(value), "utf8") <= 128 * 1024; } catch { return false; } }
const invalid = (): never => { throw new Error("ASSISTANT_MAIN_CONTROL_INVALID"); };
export function parseBrowserClaim(value: unknown): BrowserMainControlRequest {
  if (!closed(value, ["deliveryId", "action"], ["pageId", "snapshotId", "elementRef", "url", "elementName", "operation", "value", "direction"]) || typeof value.deliveryId !== "string" || !/^[0-9a-f]{32}$/.test(value.deliveryId) || !isBrowserAction(value.action)) return invalid();
  const keys: Record<BrowserAction, string[]> = {
    browser_state: [], browser_open: ["url"], browser_ensure: ["url"], browser_select: ["pageId"], browser_show: [], browser_read: ["pageId"], browser_navigate: ["pageId", "url"],
    browser_back: ["pageId"], browser_forward: ["pageId"], browser_reload: ["pageId"], browser_scroll: ["pageId", "direction"],
    browser_interact: ["pageId", "snapshotId", "elementRef", "url", "elementName", "operation", ...(value.operation === "fill" ? ["value"] : [])],
  };
  if (!closed(value, ["deliveryId", "action", ...keys[value.action]]) || !bounded(value)
    || ("pageId" in value && !uuid(value.pageId)) || ("snapshotId" in value && !uuid(value.snapshotId))
    || ("elementRef" in value && !ref(value.elementRef)) || ("url" in value && !browserUrl(value.url))
    || ("elementName" in value && !str(value.elementName, 160)) || (value.action === "browser_scroll" && value.direction !== "up" && value.direction !== "down")
    || (value.action === "browser_interact" && value.operation !== "click" && value.operation !== "fill")
    || (value.action === "browser_interact" && value.operation === "fill" && (typeof value.value !== "string" || !wellFormed(value.value) || Array.from(value.value).length > 2000))) return invalid();
  return { ...value } as BrowserMainControlRequest;
}
function state(value: unknown): boolean {
  if (!closed(value, ["pages", "activePageId", "takeover"]) || !array(value.pages, 4) || typeof value.takeover !== "boolean") return false;
  const ids: string[] = [];
  for (const p of value.pages) {
    if (!closed(p, ["id", "url", "title", "loading", "canGoBack", "canGoForward"], ["loadError"]) || !uuid(p.id) || !browserUrl(p.url, true) || !str(p.title, 200)
      || typeof p.loading !== "boolean" || typeof p.canGoBack !== "boolean" || typeof p.canGoForward !== "boolean" || (Object.hasOwn(p, "loadError") && typeof p.loadError !== "boolean")) return false;
    ids.push(p.id);
  }
  return new Set(ids).size === ids.length && (value.activePageId === null ? ids.length === 0 : ids.includes(value.activePageId as string));
}
function snapshot(value: unknown, request: BrowserMainControlRequest): boolean {
  if (!closed(value, ["pageId", "snapshotId", "url", "title", "untrusted", "text", "elements"]) || !("pageId" in request) || value.pageId !== request.pageId || !uuid(value.snapshotId)
    || !browserUrl(value.url) || !str(value.title, 200) || value.untrusted !== true || !str(value.text, 8000) || !array(value.elements, 80)) return false;
  const refs: string[] = [];
  for (const e of value.elements) { if (!closed(e, ["ref", "role", "name"]) || !ref(e.ref) || !str(e.role, 40) || !str(e.name, 160)) return false; refs.push(e.ref as string); }
  return new Set(refs).size === refs.length;
}
export function browserError(request: BrowserMainControlRequest, code: string): Record<string, unknown> {
  return { schemaVersion: 1, operation: request.action.slice(8), code: browserErrorCodes.includes(code) ? code : "BROWSER_ACTION_OUTCOME_UNKNOWN" };
}
export function browserControlResult(request: BrowserMainControlRequest, value: unknown): Record<string, unknown> {
  const fail = () => browserError(request, "BROWSER_ACTION_OUTCOME_UNKNOWN");
  const key = request.action === "browser_read" ? "snapshot" : "state";
  if (!closed(value, ["schemaVersion", "operation", "code"], [key]) || value.schemaVersion !== 1 || value.operation !== request.action.slice(8) || typeof value.code !== "string") return fail();
  if (value.code === "ok") {
    if (!Object.hasOwn(value, key) || !(key === "state" ? state(value[key]) : snapshot(value[key], request)) || !bounded(value)) return fail();
  } else if (!browserErrorCodes.includes(value.code) || Object.hasOwn(value, key)) return fail();
  return JSON.parse(JSON.stringify(value)) as Record<string, unknown>;
}
