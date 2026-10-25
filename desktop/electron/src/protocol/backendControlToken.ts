export type BackendControlProcessIdentity = {
  pid: number;
  createTime: number;
};

type ProcessIdentity = BackendControlProcessIdentity | null;
type PendingToken = { identity: ProcessIdentity; promise: Promise<string> };
type CachedToken = { identity: BackendControlProcessIdentity; token: string };

class ControlContextChangedError extends Error {
  constructor() {
    super("backend control context changed");
  }
}

function sameIdentity(left: ProcessIdentity, right: ProcessIdentity): boolean {
  return left === null || right === null
    ? left === right
    : left.pid === right.pid && left.createTime === right.createTime;
}

function abortedError(): Error {
  const error = new Error("backend control token wait aborted");
  error.name = "AbortError";
  return error;
}

function waitForToken(promise: Promise<string>, signal?: AbortSignal): Promise<string> {
  if (!signal) return promise;
  return new Promise((resolve, reject) => {
    let listening = true;
    const cleanup = () => {
      if (!listening) return;
      listening = false;
      signal.removeEventListener("abort", onAbort);
    };
    const onAbort = () => {
      cleanup();
      reject(abortedError());
    };
    signal.addEventListener("abort", onAbort, { once: true });
    if (signal.aborted) onAbort();
    // Always observe the shared request, even if this waiter has already left.
    promise.then((token) => {
      cleanup();
      resolve(token);
    }, (error: unknown) => {
      cleanup();
      reject(error);
    });
  });
}

/** Owns a backend token only within one workspace, origin and live process identity. */
export class BackendControlTokenOwner {
  private readonly workspaceRoot: string;
  private readonly launcherOrigin: string;
  private readonly readBackendIdentity: () => ProcessIdentity;
  private readonly fetchControlToken: () => Promise<string>;
  private cached: CachedToken | undefined;
  private pending: PendingToken | undefined;

  constructor(options: {
    workspaceRoot: string;
    launcherOrigin: string;
    readBackendIdentity: () => BackendControlProcessIdentity | null;
    fetchControlToken: () => Promise<string>;
  }) {
    this.workspaceRoot = options.workspaceRoot;
    this.launcherOrigin = new URL(options.launcherOrigin).origin;
    this.readBackendIdentity = options.readBackendIdentity;
    this.fetchControlToken = options.fetchControlToken;
  }

  isForScope(workspaceRoot: string, launcherOrigin: string): boolean {
    if (workspaceRoot !== this.workspaceRoot) return false;
    try {
      return new URL(launcherOrigin).origin === this.launcherOrigin;
    } catch {
      return false;
    }
  }

  async resolve(options: { forceRefresh?: boolean; signal?: AbortSignal } = {}): Promise<string> {
    for (let attempt = 0; attempt < 2; attempt += 1) {
      if (options.signal?.aborted) throw abortedError();
      const identity = this.currentIdentity();
      if (this.cached && !sameIdentity(this.cached.identity, identity)) this.cached = undefined;
      if (attempt === 0 && options.forceRefresh) this.cached = undefined;
      if (options.signal?.aborted) throw abortedError();
      if (this.cached) return this.cached.token;

      const pending = this.pending && sameIdentity(this.pending.identity, identity)
        ? this.pending
        : this.startFetch(identity);
      try {
        const token = await waitForToken(pending.promise, options.signal);
        if (options.signal?.aborted) throw abortedError();
        if (!sameIdentity(identity, this.currentIdentity())) throw new ControlContextChangedError();
        return token;
      } catch (error) {
        if (options.signal?.aborted) throw abortedError();
        if (!(error instanceof ControlContextChangedError) || attempt === 1) throw error;
      }
    }
    throw new ControlContextChangedError();
  }

  private currentIdentity(): ProcessIdentity {
    const identity = this.readBackendIdentity();
    if (!identity || !Number.isInteger(identity.pid) || identity.pid <= 0
      || !Number.isFinite(identity.createTime) || identity.createTime <= 0) return null;
    // Snapshot values: callers may reuse and mutate their process metadata object.
    return { pid: identity.pid, createTime: identity.createTime };
  }

  private startFetch(identity: ProcessIdentity): PendingToken {
    const pending: PendingToken = {
      identity,
      promise: Promise.resolve().then(async () => {
        let result: string;
        try {
          result = await this.fetchControlToken();
        } catch {
          if (!sameIdentity(identity, this.currentIdentity())) throw new ControlContextChangedError();
          throw new Error("backend control token fetch failed");
        }
        if (!sameIdentity(identity, this.currentIdentity())) throw new ControlContextChangedError();
        const token = typeof result === "string" ? result.trim() : "";
        if (!token) throw new Error("backend control token is empty");
        if (identity && this.pending === pending) this.cached = { identity, token };
        return token;
      }).finally(() => {
        // An earlier process request must never clear a newer process's slot.
        if (this.pending === pending) this.pending = undefined;
      })
    };
    this.pending = pending;
    return pending;
  }
}
