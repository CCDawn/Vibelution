import { boundedDesktopControlFetch } from "../protocol/boundedFetch.js";
import { fetchLauncherControlToken } from "../protocol/desktopActionClient.js";

export type RuntimeSceneElectronEvent = {
  eventCode: string;
  message: string;
  fields: Record<string, string | number | boolean>;
};

export type RuntimeSceneBridgeOptions = {
  launcherOrigin: string;
  controlToken: string;
  maxBufferedEvents: number;
  fetchImpl?: typeof fetch;
  /** Resolve the current backend's paired origin/token before each queued POST. */
  resolveControlContext?: () => Promise<{ launcherOrigin: string; controlToken: string }>;
  /**
   * Overrides how a fresh control token is obtained after a 401/403. The
   * default re-fetches the launcher `/api/control-token` route from this shell
   * process (token-exempt GET, loopback-source gated) via the same production
   * helper `resolveDesktopActionLoopContext` uses for forced refreshes.
   */
  refreshControlToken?: () => Promise<string>;
  /** Monotonic millisecond clock; injectable so backoff tests need no fake timers. */
  clock?: () => number;
  /** Backoff before the next refresh attempt after one failed/unhelpful refresh. */
  tokenRefreshBackoffBaseMs?: number;
  /** Upper bound of the exponential refresh backoff. */
  tokenRefreshBackoffMaxMs?: number;
  /** Consecutive failed refresh cycles before the cooldown window starts. */
  tokenRefreshMaxFailures?: number;
  /** Cooldown window during which no refresh is attempted at all. */
  tokenRefreshCooldownMs?: number;
};

const DEFAULT_TOKEN_REFRESH_BACKOFF_BASE_MS = 1_000;
const DEFAULT_TOKEN_REFRESH_BACKOFF_MAX_MS = 30_000;
const DEFAULT_TOKEN_REFRESH_MAX_FAILURES = 3;
const DEFAULT_TOKEN_REFRESH_COOLDOWN_MS = 60_000;

/**
 * Structured POST failure carrying the HTTP status, so callers (and this
 * module's auth self-heal) can distinguish credential rejections from
 * transport failures without parsing the message.
 */
export class RuntimeSceneEventPostError extends Error {
  readonly status: number;

  constructor(status: number) {
    super(`runtime scene event rejected: ${status}`);
    this.name = "RuntimeSceneEventPostError";
    this.status = status;
  }
}

/**
 * A structurally rejected drop recorded by one flush cycle: the HTTP status
 * that permanently refused the event, plus the bounded event object itself.
 */
export type RuntimeSceneEventDrop = {
  status: number;
  event: RuntimeSceneElectronEvent;
};

/**
 * Raised when a structurally rejected event (backend 400/404/422: the event
 * payload itself can never be accepted by this endpoint) is dropped from the
 * queue. `event` is the bounded event object that was enqueued by the failing
 * `record()` call (reference equality), so its caller can persist the event
 * through its own supervisor-event fallback. `droppedEvents` lists every
 * event dropped by the same flush cycle, including the one in `event`.
 */
export class RuntimeSceneEventRejectedError extends Error {
  readonly status: number;
  readonly event: RuntimeSceneElectronEvent;
  readonly droppedEvents: readonly RuntimeSceneElectronEvent[];

  constructor(firstDrop: RuntimeSceneEventDrop, furtherDrops: readonly RuntimeSceneEventDrop[] = []) {
    super(`runtime scene event permanently rejected: ${firstDrop.status}`);
    this.name = "RuntimeSceneEventRejectedError";
    this.status = firstDrop.status;
    this.event = firstDrop.event;
    this.droppedEvents = [firstDrop.event, ...furtherDrops.map((drop) => drop.event)];
  }
}

/**
 * Statuses that mean the event itself can never be accepted by the runtime
 * scene endpoint (unknown event code, malformed payload, wrong route). Unlike
 * auth (401/403, self-healed by token refresh) or transient failures
 * (429/5xx/network, retried by a later flush), retrying these events is
 * pointless: leaving them queued would poison the head of the buffer and
 * silently block every event behind them forever.
 */
const STRUCTURAL_REJECTION_STATUSES: ReadonlySet<number> = new Set([400, 404, 422]);

function isStructuralRejection(error: unknown): error is RuntimeSceneEventPostError {
  return (
    error instanceof RuntimeSceneEventPostError &&
    STRUCTURAL_REJECTION_STATUSES.has(error.status)
  );
}

function isAuthRejectionStatus(status: number): boolean {
  return status === 401 || status === 403;
}

export function electronEventPayload(event: RuntimeSceneElectronEvent) {
  return {
    component: "electron_launcher",
    phase: "desktop_supervisor",
    eventCode: event.eventCode,
    message: event.message,
    fields: event.fields
  };
}

export class RuntimeSceneBridge {
  private readonly queue: RuntimeSceneElectronEvent[] = [];
  private flushPromise: Promise<void> | null = null;
  private inFlight: RuntimeSceneElectronEvent | null = null;

  /** Current control token; rotated in place after a successful self-heal refresh. */
  private controlToken: string;
  private readonly refreshTokenSource: () => Promise<string>;
  private readonly currentTimeMs: () => number;
  private readonly tokenRefreshBackoffBaseMs: number;
  private readonly tokenRefreshBackoffMaxMs: number;
  private readonly tokenRefreshMaxFailures: number;
  private readonly tokenRefreshCooldownMs: number;

  // Single-flight refresh slot. `runRefreshAttempt` performs its own failure
  // accounting exactly once, so every joined awaiter observes the same outcome
  // without double-counting toward backoff/cooldown.
  private refreshAttempt: Promise<string | null> | null = null;
  private refreshFailures = 0;
  private refreshEligibleAtMs = 0;
  private refreshCooldownUntilMs = 0;

  constructor(private readonly options: RuntimeSceneBridgeOptions) {
    this.controlToken = options.controlToken;
    this.refreshTokenSource =
      options.refreshControlToken ??
      (() =>
        fetchLauncherControlToken({
          launcherOrigin: options.launcherOrigin,
          fetchImpl: options.fetchImpl
        }));
    this.currentTimeMs = options.clock ?? (() => Date.now());
    this.tokenRefreshBackoffBaseMs = sanitizeDelay(
      options.tokenRefreshBackoffBaseMs,
      DEFAULT_TOKEN_REFRESH_BACKOFF_BASE_MS
    );
    this.tokenRefreshBackoffMaxMs = Math.max(
      this.tokenRefreshBackoffBaseMs,
      sanitizeDelay(options.tokenRefreshBackoffMaxMs, DEFAULT_TOKEN_REFRESH_BACKOFF_MAX_MS)
    );
    this.tokenRefreshMaxFailures = Math.max(
      1,
      Math.floor(options.tokenRefreshMaxFailures ?? DEFAULT_TOKEN_REFRESH_MAX_FAILURES)
    );
    this.tokenRefreshCooldownMs = sanitizeDelay(
      options.tokenRefreshCooldownMs,
      DEFAULT_TOKEN_REFRESH_COOLDOWN_MS
    );
  }

  async record(event: RuntimeSceneElectronEvent): Promise<void> {
    const bounded = this.bound(event);
    this.queue.push(bounded);
    this.trimQueue();
    try {
      await this.flush();
    } catch (error) {
      // A structurally rejected event (backend 400/404/422) has already been
      // dropped from the queue and can never be delivered; surface that to
      // this caller (reference equality against the bounded copy it enqueued)
      // so the supervisor-event local fallback in the shell can persist it.
      // All other failures keep the legacy silent-retry semantics: the failed
      // head stays queued and will be retried by a later record/flush call.
      if (
        error instanceof RuntimeSceneEventRejectedError &&
        error.droppedEvents.includes(bounded)
      ) {
        throw error;
      }
    }
  }

  async flush(): Promise<void> {
    if (this.flushPromise !== null) {
      return this.flushPromise;
    }
    // Start the owner in a microtask after publishing its promise. This lets
    // flushQueue release the exact owner before its promise resolves, so a
    // record arriving in the settle boundary can acquire a fresh owner
    // instead of observing an already-completed promise forever.
    let flushPromise!: Promise<void>;
    flushPromise = Promise.resolve().then(() => this.flushQueue(flushPromise));
    this.flushPromise = flushPromise;
    try {
      await flushPromise;
    } finally {
      if (this.flushPromise === flushPromise) {
        this.flushPromise = null;
      }
    }
  }

  bufferedCount(): number {
    return this.queue.length;
  }

  private async flushQueue(ownerPromise: Promise<void>): Promise<void> {
    const dropped: RuntimeSceneEventDrop[] = [];
    try {
      while (this.queue.length > 0) {
        const next = this.queue[0];
        this.inFlight = next;
        let rejectionStatus: number | null = null;
        try {
          await this.post(next);
        } catch (error) {
          // A structural rejection (400/404/422) means this event can never
          // be accepted. Drop it instead of throwing out of the loop: a
          // poisoned head would otherwise block every later event forever.
          // Transient failures (429/5xx/network) still throw and leave the
          // head queued for the legacy silent retry.
          if (!isStructuralRejection(error)) {
            throw error;
          }
          rejectionStatus = error.status;
        } finally {
          this.inFlight = null;
        }
        // Only the flush that owns this head may remove it. Other records can
        // append concurrently, but they cannot shift the in-flight event.
        this.dequeue(next);
        if (rejectionStatus !== null) {
          // 历史滞留毒头的丢弃暂无本地留痕，接线点留待 main.ts 空闲后。
          dropped.push({ status: rejectionStatus, event: next });
          continue;
        }
      }
    } finally {
      // Release before resolving ownerPromise. A new record that arrives in
      // the promise-settlement microtask therefore gets a new owner and drains
      // without requiring a third external flush call.
      if (this.flushPromise === ownerPromise) {
        this.flushPromise = null;
      }
    }
    if (dropped.length > 0) {
      // The owner promise rejects with the drop record so awaiting callers
      // (record()) can match their own bounded event by reference and
      // re-throw it to their caller for the local fallback path.
      throw new RuntimeSceneEventRejectedError(dropped[0], dropped.slice(1));
    }
  }

  private dequeue(event: RuntimeSceneElectronEvent): void {
    if (this.queue[0] === event) {
      this.queue.shift();
    } else {
      const index = this.queue.indexOf(event);
      if (index >= 0) {
        this.queue.splice(index, 1);
      }
    }
  }

  private trimQueue(): void {
    const maxBufferedEvents = Math.max(0, Math.floor(this.options.maxBufferedEvents));
    while (this.queue.length > maxBufferedEvents) {
      // Never evict a request while its POST is in flight. If that request
      // fails, it must remain the retryable queue head; evict the oldest
      // pending event instead.
      const protectedHead = this.inFlight !== null && this.queue[0] === this.inFlight;
      if (protectedHead && this.queue.length === 1) {
        return;
      }
      this.queue.splice(protectedHead ? 1 : 0, 1);
    }
  }

  private async post(event: RuntimeSceneElectronEvent): Promise<void> {
    let response = await this.postEvent(event);
    this.discardResponseBody(response);
    if (isAuthRejectionStatus(response.status)) {
      // A rotated backend token is the expected cause of a 401/403 here.
      // Refresh once (single-flight, backoff and cooldown gated) and retry
      // this event with the new token before giving the head back to the
      // queue for the legacy silent retry behavior.
      const refreshedToken = await this.tryRefreshControlToken();
      if (refreshedToken !== null) {
        response = await this.postEvent(event);
        this.discardResponseBody(response);
      }
    }
    if (!response.ok) {
      throw new RuntimeSceneEventPostError(response.status);
    }
  }

  private async postEvent(event: RuntimeSceneElectronEvent): Promise<Response> {
    let launcherOrigin = this.options.launcherOrigin;
    if (this.options.resolveControlContext) {
      const context = await this.options.resolveControlContext();
      if (!context.controlToken.trim()) throw new Error("runtime scene control context is missing a token");
      launcherOrigin = context.launcherOrigin;
      this.controlToken = context.controlToken;
    }
    return boundedDesktopControlFetch({
      fetchImpl: this.options.fetchImpl,
      resource: `${new URL(launcherOrigin).origin}/api/launcher/runtime-scene/events`,
      operation: "runtime scene event",
      init: {
        method: "POST",
        headers: {
          "content-type": "application/json",
          "X-Vibelution-Control-Token": this.controlToken
        },
        body: JSON.stringify(electronEventPayload(event))
      }
    });
  }

  private discardResponseBody(response: Response): void {
    // The status is the complete acknowledgement. Release an unread body so
    // even a server that never finishes its response cannot retain a socket.
    void response.body?.cancel().catch(() => undefined);
  }

  /**
   * Best-effort control-token refresh. Returns the new token when it actually
   * rotated (caller should retry), or null when refresh is gated (backoff /
   * cooldown), failed, or returned an unchanged token — in all null cases the
   * caller falls back to the existing silent retry semantics.
   */
  private async tryRefreshControlToken(): Promise<string | null> {
    const now = this.currentTimeMs();
    if (now < this.refreshCooldownUntilMs || now < this.refreshEligibleAtMs) {
      return null;
    }
    if (this.refreshAttempt === null) {
      this.refreshAttempt = this.runRefreshAttempt();
    }
    return this.refreshAttempt;
  }

  private async runRefreshAttempt(): Promise<string | null> {
    try {
      const token = String((await this.refreshTokenSource()) ?? "").trim();
      if (!token) {
        throw new Error("refreshed control token is empty");
      }
      if (token === this.controlToken) {
        // No rotation happened; retrying with the identical token cannot
        // succeed, so keep the head queued and back off.
        this.noteRefreshFailure();
        return null;
      }
      this.controlToken = token;
      this.refreshFailures = 0;
      this.refreshEligibleAtMs = 0;
      return token;
    } catch {
      this.noteRefreshFailure();
      return null;
    } finally {
      this.refreshAttempt = null;
    }
  }

  private noteRefreshFailure(): void {
    const now = this.currentTimeMs();
    this.refreshFailures += 1;
    const backoffMs = Math.min(
      this.tokenRefreshBackoffBaseMs * 2 ** (this.refreshFailures - 1),
      this.tokenRefreshBackoffMaxMs
    );
    this.refreshEligibleAtMs = now + backoffMs;
    if (this.refreshFailures >= this.tokenRefreshMaxFailures) {
      this.refreshCooldownUntilMs = now + this.tokenRefreshCooldownMs;
      this.refreshFailures = 0;
    }
  }

  private bound(event: RuntimeSceneElectronEvent): RuntimeSceneElectronEvent {
    return {
      eventCode: event.eventCode.slice(0, 120),
      message: event.message.slice(0, 500),
      fields: Object.fromEntries(
        Object.entries(event.fields).map(([key, value]) => [
          key.slice(0, 80),
          typeof value === "string" ? value.slice(0, 500) : value
        ])
      )
    };
  }
}

function sanitizeDelay(value: number | undefined, defaultValue: number): number {
  const parsed = Math.round(value ?? defaultValue);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : defaultValue;
}
