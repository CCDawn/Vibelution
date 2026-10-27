import type { IpcMainInvokeEvent } from "electron";
import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";
import type { AssistantProjectRegistrySnapshot } from "../assistant/projectRegistry.js";
import type { RegistryEntry, RegistryPayload } from "../lifecycle/instanceRegistryStore.js";
import { assertLocalHttpUrl } from "../security/urlPolicy.js";
import type { ElectronWindowProvider } from "../windows/electronWindowProvider.js";
import type { HumanAttentionSource } from "./humanAttentionNotifications.js";
import type { LegacyReminderSourceBinding } from "./legacyReminderSourceFence.js";

type ProjectConnection = { snapshot(): AssistantProjectRegistrySnapshot };
type ResolverOptions = {
  windowProvider(): ElectronWindowProvider | null;
  projectConnection(): ProjectConnection | null;
  readInstances(): Promise<RegistryPayload>;
};

function rootState(path: unknown): { physical: string; physicalIdentity: { device: string; inode: string } } {
  if (typeof path !== "string" || !path || path !== path.trim() || path.includes("\0") || !isAbsolute(path)) throw new Error();
  const physical = realpathSync.native(path);
  const stat = statSync(physical, { bigint: true });
  if (!stat.isDirectory() || stat.dev === 0n || stat.ino === 0n) throw new Error();
  return { physical: process.platform === "win32" ? physical.toLowerCase() : physical,
    physicalIdentity: { device: stat.dev.toString(), inode: stat.ino.toString() } };
}

function registryOrigin(value: unknown): string {
  if (typeof value !== "string" || !value || value !== value.trim()) throw new Error();
  const url = new URL(value);
  if (url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error();
  assertLocalHttpUrl(url.href, url.origin);
  return url.origin;
}

function running(entry: RegistryEntry): boolean {
  return entry.status === "steady" && entry.phase === "steady" && entry.desiredState === "open"
    && entry.portLeaseStatus === "held"
    && (entry.cleanupInProgress === undefined || entry.cleanupInProgress === false)
    && Number.isSafeInteger(entry.generation) && Number(entry.generation) > 0
    && Number.isSafeInteger(entry.port) && Number(entry.port) > 0 && Number(entry.port) < 65536;
}

/** A stable representation; registry ordering is not an identity. */
function canonical(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(canonical);
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))
    .map(([key, item]) => [key, canonical(item)]));
  return value;
}

/**
 * Attribution only. Registry state does not prove process liveness, a stopped
 * sender, all sources, or permission to enable a replacement consumer.
 */
export function createLegacyReminderSourceResolver(options: ResolverOptions) {
  return async (event: IpcMainInvokeEvent, source: HumanAttentionSource): Promise<LegacyReminderSourceBinding | null> => {
    try {
      const provider = options.windowProvider(), projects = options.projectConnection();
      if (!provider || !projects || !source || typeof source.instanceId !== "string" || !source.instanceId) return null;
      const documentCurrent = () => {
        const frame = event.senderFrame;
        if (!frame || frame !== event.sender.mainFrame || options.windowProvider() !== provider
            || options.projectConnection() !== projects || new URL(frame.url).origin !== source.origin
            || provider.trustedWorkbenchInstanceForSender(event.sender, frame.url) !== source.instanceId) return false;
        const target = provider.notificationTargetForSender(event.sender, frame.url);
        return Boolean(target?.isLive() && target.documentToken === source.documentToken);
      };
      if (!documentCurrent()) return null;
      const projectBefore = projects.snapshot();
      if (projectBefore.schemaVersion !== 1 || !Number.isSafeInteger(projectBefore.revision) || projectBefore.revision < 0
          || !projectBefore.projects || typeof projectBefore.projects !== "object" || Array.isArray(projectBefore.projects)) return null;
      const projectRevision = projectBefore.revision;
      const projectFingerprint = JSON.stringify(canonical(projectBefore.projects));
      const projectEntries = Object.entries(projectBefore.projects);
      const first = await options.readInstances();
      if (!documentCurrent()) return null;
      const registryFingerprint = JSON.stringify(canonical(first.instances));
      const entries = Object.entries(first.instances);
      const matching: Array<[string, RegistryEntry]> = [];
      for (const [id, row] of entries) {
        if (!row || typeof row !== "object") return null;
        // Unknown live/in-flight origins prevent a complete uniqueness check.
        if (!row.url) {
          if (!["closed", "failed"].includes(String(row.status ?? ""))) return null;
          continue;
        }
        let origin: string;
        try { origin = registryOrigin(row.url); } catch { return null; }
        if (origin === source.origin) matching.push([id, row]);
      }
      if (matching.length !== 1) return null;
      const [id, entry] = matching[0];
      if (source.instanceId !== "main" && id !== source.instanceId) return null;
      if (!running(entry) || Number(new URL(entry.url!).port) !== entry.port) return null;
      const sourceRoot = entry.projectRoot;
      const root = rootState(sourceRoot);
      const candidates = projectEntries.filter(([, path]) => rootState(path).physical === root.physical);
      if (candidates.length !== 1) return null;
      const [projectId] = candidates[0];
      if (!projectId || projectId !== projectId.trim()) return null;
      const second = await options.readInstances();
      const projectAfter = projects.snapshot();
      if (!documentCurrent() || projectAfter.schemaVersion !== 1 || projectAfter.revision !== projectRevision
          || JSON.stringify(canonical(projectAfter.projects)) !== projectFingerprint
          || JSON.stringify(canonical(second.instances)) !== registryFingerprint
          || JSON.stringify(rootState(sourceRoot)) !== JSON.stringify(root)
          || JSON.stringify(rootState(projectAfter.projects[projectId])) !== JSON.stringify(root)) return null;
      return { projectId, instanceId: source.instanceId, physicalRoot: root.physical, physicalIdentity: root.physicalIdentity };
    } catch { return null; }
  };
}
