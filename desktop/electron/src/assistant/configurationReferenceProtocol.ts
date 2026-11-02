import { isAbsolute } from "node:path";

/** Private host-to-main broker only. These actions are not renderer/model APIs. */
export type ConfigurationReferenceRequest = { deliveryId: string; contextId: string } & (
  | { action: "configuration_reference_acquire" }
  | { action: "configuration_reference_validate" | "configuration_reference_release"; leaseId: string; snapshotDigest: string });
export type ConfigurationReferenceProject = { registrationId: string; baseProjectId: string; root: string; active: boolean };
export type ConfigurationReferenceSnapshot = { schemaVersion: 1; leaseId: string; revision: number; snapshotDigest: string;
  complete: true; projects: ConfigurationReferenceProject[]; nativeAssistantRoot: string };
export type ConfigurationReferenceResult = ConfigurationReferenceSnapshot
  | { schemaVersion: 1; complete: false; code: "busy" | "unavailable" }
  | { schemaVersion: 1; leaseId: string; valid: true; revision: number; snapshotDigest: string }
  | { schemaVersion: 1; leaseId: string; valid: false }
  | { schemaVersion: 1; leaseId: string; released: boolean };
/** Created by AssistantHost for its exact native Job, never from request data. */
export type ConfigurationReferenceHostContext = Readonly<{
  generationId: string; agentId: string; sessionId: string; nativeAssistantRoot: string;
  signal: AbortSignal;
  check(): void;
  /** Main-only retention, so transport recovery never terminates a live scope. */
  retainLease(): () => void;
  /** Exact native context proof; neither request metadata nor a command ACK. */
  readWorkComplete(contextId: string): Promise<boolean>;
  ackWorkComplete(contextId: string): Promise<void>;
  /** Resolve only after the captured Job has exited and its output has drained. */
  drain(signal?: AbortSignal): Promise<void>;
}>;
const actions = new Set(["configuration_reference_acquire", "configuration_reference_validate", "configuration_reference_release"]);
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const opaque = (value: unknown): value is string => typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9_.:-]{0,159}$/.test(value);
const root = (value: unknown): value is string => typeof value === "string" && value === value.trim() && !value.includes("\0") && isAbsolute(value);
function closed(value: unknown, fields: string[]): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value) || ![Object.prototype, null].includes(Object.getPrototypeOf(value))) return false;
  const descriptors = Object.getOwnPropertyDescriptors(value);
  return Reflect.ownKeys(value).length === fields.length && fields.every(key => {
    const descriptor = descriptors[key];
    return descriptor && Object.hasOwn(descriptor, "value") && descriptor.enumerable;
  });
}
export function isConfigurationReferenceRequest(value: { action: string }): value is ConfigurationReferenceRequest {
  return actions.has(value.action);
}
export function parseConfigurationReferenceRequest(value: unknown): ConfigurationReferenceRequest {
  const action = value && typeof value === "object" ? Object.getOwnPropertyDescriptor(value, "action")?.value : undefined;
  const fields = ["deliveryId", "action", "contextId", ...(action === "configuration_reference_acquire" ? [] : ["leaseId", "snapshotDigest"])];
  if (!closed(value, fields) || typeof action !== "string" || !actions.has(action)
      || typeof value.deliveryId !== "string" || !/^[a-f0-9]{32}$/.test(value.deliveryId)
      || typeof value.contextId !== "string" || !/^cfg-[a-f0-9-]{32,64}$/.test(value.contextId)
      || action !== "configuration_reference_acquire" && (!hash(value.leaseId) || !hash(value.snapshotDigest))) {
    throw new Error("ASSISTANT_MAIN_CONTROL_INVALID");
  }
  return { deliveryId: value.deliveryId, contextId: value.contextId, action,
    ...(action === "configuration_reference_acquire" ? {} : { leaseId: value.leaseId, snapshotDigest: value.snapshotDigest }) } as ConfigurationReferenceRequest;
}
export function configurationReferenceResult(request: ConfigurationReferenceRequest, value: unknown): ConfigurationReferenceResult {
  const unknown: ConfigurationReferenceResult = request.action === "configuration_reference_acquire"
    ? { schemaVersion: 1, complete: false, code: "unavailable" }
    : request.action === "configuration_reference_validate" ? { schemaVersion: 1, leaseId: request.leaseId, valid: false }
    : { schemaVersion: 1, leaseId: request.leaseId, released: false };
  if (request.action === "configuration_reference_acquire") {
    if (closed(value, ["schemaVersion", "complete", "code"]) && value.schemaVersion === 1 && value.complete === false
        && (value.code === "busy" || value.code === "unavailable")) return { schemaVersion: 1, complete: false, code: value.code };
    if (!closed(value, ["schemaVersion", "leaseId", "revision", "snapshotDigest", "complete", "projects", "nativeAssistantRoot"])
        || value.schemaVersion !== 1 || !hash(value.leaseId) || !hash(value.snapshotDigest) || value.complete !== true
        || !Number.isSafeInteger(value.revision) || Number(value.revision) < 0 || !root(value.nativeAssistantRoot)
        || !Array.isArray(value.projects) || value.projects.length > 32768) return unknown;
    const seen = new Set<string>();
    const projects: ConfigurationReferenceProject[] = [];
    for (const row of value.projects) {
      if (!closed(row, ["registrationId", "baseProjectId", "root", "active"]) || !opaque(row.registrationId)
          || !opaque(row.baseProjectId) || !root(row.root) || typeof row.active !== "boolean" || seen.has(row.registrationId)) return unknown;
      seen.add(row.registrationId);
      projects.push({ registrationId: row.registrationId, baseProjectId: row.baseProjectId, root: row.root, active: row.active });
    }
    if (Buffer.byteLength(JSON.stringify(value), "utf8") > 4 * 1024 * 1024) return unknown;
    return { schemaVersion: 1, leaseId: value.leaseId, revision: value.revision as number, snapshotDigest: value.snapshotDigest,
      complete: true, projects, nativeAssistantRoot: value.nativeAssistantRoot };
  }
  if (request.action === "configuration_reference_validate") {
    if (closed(value, ["schemaVersion", "leaseId", "valid", "revision", "snapshotDigest"]) && value.schemaVersion === 1
        && value.leaseId === request.leaseId && value.valid === true && value.snapshotDigest === request.snapshotDigest
        && Number.isSafeInteger(value.revision) && Number(value.revision) >= 0) return { schemaVersion: 1, leaseId: request.leaseId,
          valid: true, revision: value.revision as number, snapshotDigest: request.snapshotDigest };
    return unknown;
  }
  if (closed(value, ["schemaVersion", "leaseId", "released"]) && value.schemaVersion === 1 && value.leaseId === request.leaseId
      && typeof value.released === "boolean") return { schemaVersion: 1, leaseId: request.leaseId, released: value.released };
  return unknown;
}
