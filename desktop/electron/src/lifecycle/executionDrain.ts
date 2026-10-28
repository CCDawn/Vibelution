/** In-memory observation only. The caller must separately fence new work. */
export class ExecutionDrain {
  private readonly active = new Set<Promise<unknown>>();

  track<T>(work: () => Promise<T>): Promise<T> {
    // Enrol synchronously, including while work is waiting to start.
    let finish!: () => void;
    const completion = new Promise<void>(resolve => { finish = resolve; });
    this.active.add(completion);
    try {
      return Promise.resolve(work()).finally(() => { this.active.delete(completion); finish(); });
    } catch (error) {
      this.active.delete(completion);
      finish();
      throw error;
    }
  }

  /** Drain enrolled work, including work enrolled while it settles. Caller fences new admissions. */
  async capture(): Promise<void> {
    while (this.active.size) await Promise.all([...this.active]);
  }
}
