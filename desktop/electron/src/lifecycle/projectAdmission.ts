import { realpathSync, statSync } from "node:fs";
import { isAbsolute } from "node:path";

type Identity = Readonly<{ root: string; object: string }>;
function identity(root: string): Identity {
  if (typeof root !== "string" || !isAbsolute(root) || root.includes("\0")) throw new Error("PROJECT_ADMISSION_UNKNOWN");
  const canonical = realpathSync.native(root);
  const info = statSync(canonical, { bigint: true });
  if (!info.isDirectory() || info.dev <= 0n || info.ino <= 0n || info.birthtimeNs <= 0n) throw new Error("PROJECT_ADMISSION_UNKNOWN");
  return { root: process.platform === "win32" ? canonical.toLowerCase() : canonical,
    object: JSON.stringify([info.dev.toString(), info.ino.toString(), info.birthtimeNs.toString()]) };
}
const same = (a: Identity, b: Identity) => a.root === b.root && a.object === b.object;
const intersects = (a: Identity, b: Identity) => a.root === b.root || a.object === b.object;

/** All registry rows must have an attributable physical directory. */
export function registeredInstancesForPhysicalRoot(rows: Record<string, { projectRoot?: unknown }>, root: string): string[] {
  const target = identity(root);
  const ids: string[] = [];
  for (const [id, row] of Object.entries(rows)) {
    if (!id.trim() || !row || typeof row !== "object" || typeof row.projectRoot !== "string") throw new Error("PROJECT_ADMISSION_UNKNOWN");
    if (same(identity(row.projectRoot), target)) ids.push(id);
  }
  if (!same(target, identity(root))) throw new Error("PROJECT_ADMISSION_UNKNOWN");
  return ids.sort();
}

export type ProjectAdmissionTicket = {
  /** Bind only to a root resolved from trusted project/instance authority. */
  bind(root: string): void;
  /** Recheck before every process spawn or window side effect. */
  check(root?: string): void;
  finish(): void;
};
export type ProjectAdmissionSeal = { root: string; readonly signal: AbortSignal; check(): void; drain(): Promise<void>; release(): void };

/** Single Electron process; does not authorize writes or account for other executables. */
export class ProjectAdmission {
  private readonly entries = new Set<{ identity: Identity | null; done: Promise<void>; finish: () => void }>();
  private readonly seals = new Set<Identity>();
  private readonly releaseSeals = new Set<() => Promise<void>>();
  private unboundWaiting = 0;

  hasSeals(): boolean { return this.seals.size > 0; }

  /** Observe ordinary calls without changing them while no seal is held.
   * An unclassifiable new call revokes seals before running, so it cannot be
   * silently blocked or mistaken for a drained source. */
  async observe<T>(root: () => string, work: (ticket?: ProjectAdmissionTicket) => Promise<T>): Promise<T> {
    let resolved: string | undefined;
    try { resolved = root(); identity(resolved); } catch {
      // Revoke synchronously, but do not let an unknown producer enter until
      // the captured operation's real drain has completed.
      const release = [...this.releaseSeals];
      if (release.length) {
        this.unboundWaiting += 1;
        try { await Promise.all(release.map(revoke => revoke())); }
        finally { this.unboundWaiting -= 1; }
      }
    }
    if (this.seals.size && resolved !== undefined) return await this.run(() => resolved!, work);
    const ticket = this.enter();
    let bound = false;
    if (resolved !== undefined) {
      try { ticket.bind(resolved); bound = true; } catch { /* Keep an unbound observer until work settles. */ }
    }
    const observed = bound ? { ...ticket, check: (path?: string) => { if (this.seals.size) ticket.check(path); } } : undefined;
    try { return await work(observed); }
    finally { ticket.finish(); }
  }

  /** Trusted root resolution and enrollment both finish before the first await. */
  async run<T>(root: () => string, work: (ticket: ProjectAdmissionTicket) => Promise<T>): Promise<T> {
    const ticket = this.enter(root());
    try { return await work(ticket); }
    finally { ticket.finish(); }
  }

  /** Synchronous side-effect check; unknown roots fail closed while sealed. */
  assertOpen(root: string): void {
    if (!this.seals.size) return;
    const target = identity(root);
    if ([...this.seals].some(seal => intersects(seal, target))) throw new Error("PROJECT_ADMISSION_SEALED");
  }

  /** Call synchronously before the first await. Unbound entries fail sealed admission closed. */
  enter(root?: string): ProjectAdmissionTicket {
    if (root === undefined && this.seals.size) throw new Error("PROJECT_ADMISSION_UNKNOWN");
    let finish!: () => void;
    const done = new Promise<void>(resolve => { finish = resolve; });
    const entry = { identity: null as Identity | null, done, finish };
    this.entries.add(entry);
    let active = true;
    const check = (root?: string): void => {
      if (!active || !entry.identity || !same(entry.identity, identity(entry.identity.root))) throw new Error("PROJECT_ADMISSION_UNKNOWN");
      if (root !== undefined && !same(entry.identity, identity(root))) throw new Error("PROJECT_ADMISSION_UNKNOWN");
      if ([...this.seals].some(seal => intersects(seal, entry.identity!))) throw new Error("PROJECT_ADMISSION_SEALED");
    };
    const ticket: ProjectAdmissionTicket = {
      bind: rootPath => {
        if (!active || entry.identity) throw new Error("PROJECT_ADMISSION_UNKNOWN");
        entry.identity = identity(rootPath);
        check();
      },
      check,
      finish: () => { if (active) { active = false; this.entries.delete(entry); entry.finish(); } },
    };
    if (root !== undefined) {
      try { ticket.bind(root); } catch (error) { ticket.finish(); throw error; }
    }
    return ticket;
  }

  /** Trusted main caller must validate registration separately, and fence other processes separately. */
  seal(root: string, options?: { drainOnRevoke(): Promise<void> }): ProjectAdmissionSeal {
    const target = identity(root);
    if (this.unboundWaiting || [...this.entries].some(entry => !entry.identity) || [...this.seals].some(item => intersects(item, target)))
      throw new Error("PROJECT_ADMISSION_UNKNOWN");
    this.seals.add(target);
    let held = true;
    const abort = new AbortController();
    const check = () => {
      if (!held || abort.signal.aborted || !same(target, identity(target.root))) throw new Error("PROJECT_ADMISSION_UNKNOWN");
    };
    let draining: Promise<void> | undefined;
    const finish = () => { held = false; this.seals.delete(target); this.releaseSeals.delete(revoke); };
    const revoke = (): Promise<void> => {
      if (!held) return Promise.resolve();
      if (draining) return draining;
      abort.abort();
      if (!options?.drainOnRevoke) { finish(); return Promise.resolve(); }
      try {
        draining = Promise.resolve(options.drainOnRevoke()).then(finish, () => new Promise<void>(() => {}));
      } catch { draining = new Promise<void>(() => {}); }
      return draining;
    };
    this.releaseSeals.add(revoke);
    return {
      root: target.root,
      signal: abort.signal,
      check,
      drain: async () => {
        check();
        const active = [...this.entries].filter(entry => entry.identity && intersects(entry.identity, target));
        await Promise.all(active.map(entry => entry.done));
        check();
      },
      release: () => { void revoke(); },
    };
  }
}
