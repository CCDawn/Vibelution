/** In-memory observation only. The caller must separately fence new work. */
export class ExecutionDrain {
  private readonly active = new Set<Promise<unknown>>();
  private readonly idleWaiters = new Set<() => void>();

  private finish(completion: Promise<unknown>, resolve: () => void): void {
    this.active.delete(completion);
    resolve();
    if (!this.active.size) for (const notify of [...this.idleWaiters]) notify();
  }

  track<T>(work: () => Promise<T>): Promise<T> {
    // Enrol synchronously, including while work is waiting to start.
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    this.active.add(completion);
    try {
      return Promise.resolve(work()).finally(() => { this.finish(completion, finish); });
    } catch (error) {
      this.finish(completion, finish);
      throw error;
    }
  }

  /** Drain enrolled work, including work enrolled while it settles. Caller fences new admissions. */
  async capture(signal?: AbortSignal): Promise<void> {
    signal?.throwIfAborted();
    while (this.active.size) {
      await new Promise<void>((resolve, reject) => {
        const cleanup = () => { this.idleWaiters.delete(onIdle); signal?.removeEventListener("abort", onAbort); };
        const onIdle = () => { cleanup(); resolve(); };
        const onAbort = () => { cleanup(); reject(signal?.reason); };
        this.idleWaiters.add(onIdle);
        signal?.addEventListener("abort", onAbort, { once: true });
        if (signal?.aborted) onAbort();
      });
      signal?.throwIfAborted();
    }
  }
}
