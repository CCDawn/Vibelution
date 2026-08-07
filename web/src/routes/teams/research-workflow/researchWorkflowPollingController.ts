/**
 * Single-flight polling controller for research workflow events.
 * Ensures one in-flight request, generation cancel on run switch / unmount,
 * and skips full refresh when snapshot exists but events are empty.
 */

export type PollEventsPayload = {
  events?: Array<Record<string, unknown>>;
  snapshot?: Record<string, unknown> | null;
  afterSequence?: number;
};

export type PollingControllerOptions = {
  fetchEvents: (runId: string, afterSequence: number) => Promise<PollEventsPayload>;
  onEvents: (runId: string, payload: PollEventsPayload) => void | Promise<void>;
  /** Called only when new events arrived and a fuller refresh is needed. */
  onNeedsRefresh?: (runId: string) => void | Promise<void>;
  intervalMs?: number;
  now?: () => number;
};

export class ResearchWorkflowPollingController {
  private readonly fetchEvents: PollingControllerOptions["fetchEvents"];
  private readonly onEvents: PollingControllerOptions["onEvents"];
  private readonly onNeedsRefresh: PollingControllerOptions["onNeedsRefresh"];
  private readonly intervalMs: number;

  private runId = "";
  private afterSequence = 0;
  private timer: ReturnType<typeof setInterval> | null = null;
  private inFlight = false;
  private generation = 0;
  private disposed = false;
  private active = false;

  constructor(options: PollingControllerOptions) {
    this.fetchEvents = options.fetchEvents;
    this.onEvents = options.onEvents;
    this.onNeedsRefresh = options.onNeedsRefresh;
    this.intervalMs = options.intervalMs ?? 2500;
  }

  get isInFlight(): boolean {
    return this.inFlight;
  }

  get currentGeneration(): number {
    return this.generation;
  }

  get currentAfterSequence(): number {
    return this.afterSequence;
  }

  /** Switch run or clear: bumps generation, cancels logical in-flight apply. */
  setRun(runId: string, afterSequence = 0): void {
    if (this.runId === runId && this.afterSequence === afterSequence && !this.disposed) {
      return;
    }
    this.generation += 1;
    this.runId = runId;
    this.afterSequence = afterSequence;
    this.inFlight = false;
  }

  setAfterSequence(sequence: number): void {
    this.afterSequence = Math.max(0, sequence);
  }

  start(): void {
    if (this.disposed) return;
    this.active = true;
    if (this.timer != null) return;
    this.timer = setInterval(() => {
      void this.tick();
    }, this.intervalMs);
  }

  stop(): void {
    this.active = false;
    if (this.timer != null) {
      clearInterval(this.timer);
      this.timer = null;
    }
  }

  dispose(): void {
    this.disposed = true;
    this.generation += 1;
    this.stop();
    this.runId = "";
    this.inFlight = false;
  }

  /**
   * One poll cycle. Manual ticks are allowed without start() so tests and
   * immediate refresh can share the same single-flight path; the interval
   * still requires start().
   */
  async tick(): Promise<void> {
    if (this.disposed) return;
    if (!this.runId) return;
    if (this.inFlight) return;

    const gen = this.generation;
    const runId = this.runId;
    const after = this.afterSequence;
    this.inFlight = true;
    try {
      const payload = await this.fetchEvents(runId, after);
      if (this.disposed || gen !== this.generation || runId !== this.runId) {
        return;
      }
      const events = Array.isArray(payload.events) ? payload.events : [];
      if (events.length === 0) {
        // Snapshot alone must NOT force full three-endpoint refresh.
        return;
      }
      await this.onEvents(runId, payload);
      if (this.disposed || gen !== this.generation) return;
      if (this.onNeedsRefresh) {
        await this.onNeedsRefresh(runId);
      }
    } finally {
      if (gen === this.generation) {
        this.inFlight = false;
      }
    }
  }
}
