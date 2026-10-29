import { randomUUID } from "node:crypto";
import { lstatSync, readFileSync } from "node:fs";
import { writeLauncherStateFile } from "../process/workbenchBackend.js";

type Theme = "light" | "dark";
export type ThemeSnapshot = { epoch: string; revision: number; theme: Theme; writeId: string };
type Outcome = { code: "applied" | "read" | "uninitialized" | "conflict" | "unavailable" | "unknown"; snapshot?: ThemeSnapshot };

/** One main-process writer; the persisted record is the only desktop authority. */
export class ThemeAuthority {
  private tail: Promise<void> = Promise.resolve();
  private queued = 0;
  constructor(private readonly path: string, private readonly publish: (snapshot: ThemeSnapshot, source: "workbench" | "assistant" | "model") => void,
    private readonly write = writeLauncherStateFile) {}

  private enqueue(operation: () => Promise<Outcome>): Promise<Outcome> {
    if (this.queued >= 32) return Promise.resolve({ code: "unavailable" });
    this.queued += 1;
    const result = this.tail.then(operation);
    this.tail = result.then(() => { this.queued -= 1; }, () => { this.queued -= 1; });
    return result;
  }

  private readRecord(): { raw: string | null; snapshot: ThemeSnapshot | null } {
    let raw: string;
    try {
      const info = lstatSync(this.path);
      if (!info.isFile() || info.isSymbolicLink() || info.size > 4096) throw new Error("invalid theme record");
      raw = readFileSync(this.path, "utf8");
    } catch (error) {
      if ((error as NodeJS.ErrnoException).code === "ENOENT") return { raw: null, snapshot: null };
      throw error;
    }
    const data = JSON.parse(raw) as Record<string, unknown>;
    if (!data || Object.keys(data).sort().join(",") !== "epoch,revision,schemaVersion,theme,writeId" || data.schemaVersion !== 1
        || typeof data.epoch !== "string" || !/^[0-9a-f-]{36}$/.test(data.epoch)
        || !Number.isSafeInteger(data.revision) || Number(data.revision) < 1
        || typeof data.writeId !== "string" || !/^[0-9a-f]{32}$/.test(data.writeId)
        || (data.theme !== "light" && data.theme !== "dark")) throw new Error("invalid theme record");
    return { raw, snapshot: { epoch: data.epoch, revision: data.revision as number, theme: data.theme, writeId: data.writeId } };
  }

  read(): Promise<Outcome> {
    return this.enqueue(async () => {
      try { const { snapshot } = this.readRecord(); return snapshot ? { code: "read", snapshot } : { code: "uninitialized" }; }
      catch { return { code: "unavailable" }; }
    });
  }

  set(theme: Theme, expected?: Pick<ThemeSnapshot, "epoch" | "revision"> | null, signal?: AbortSignal,
    beforeCommit: () => boolean = () => true, source: "workbench" | "assistant" | "model" = "model",
    writeId: string = randomUUID().replaceAll("-", "")): Promise<Outcome> {
    return this.enqueue(async () => {
      if (signal?.aborted) return { code: "unavailable" };
      try {
        const old = this.readRecord();
        if (!beforeCommit() || signal?.aborted) return { code: "unavailable" };
        if (expected !== undefined && (expected === null ? old.snapshot !== null
          : !old.snapshot || expected.epoch !== old.snapshot.epoch || expected.revision !== old.snapshot.revision))
          return { code: "conflict", ...(old.snapshot ? { snapshot: old.snapshot } : {}) };
        if (old.snapshot && old.snapshot.revision >= Number.MAX_SAFE_INTEGER) return { code: "unavailable" };
        if (!/^[0-9a-f]{32}$/.test(writeId)) return { code: "unavailable" };
        const snapshot: ThemeSnapshot = { epoch: old.snapshot?.epoch ?? randomUUID(), revision: (old.snapshot?.revision ?? 0) + 1, theme, writeId };
        await this.write(this.path, { schemaVersion: 1, ...snapshot }, undefined, () =>
          !signal?.aborted && beforeCommit() && this.readRecord().raw === old.raw);
        try { this.publish(snapshot, source); } catch { /* A later handshake reads the committed record. */ }
        return { code: "applied", snapshot };
      } catch { return { code: "unknown" }; }
    });
  }
}
