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
};

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

  constructor(private readonly options: RuntimeSceneBridgeOptions) {}

  async record(event: RuntimeSceneElectronEvent): Promise<void> {
    const bounded = this.bound(event);
    this.queue.push(bounded);
    this.trimQueue();
    try {
      await this.flush();
    } catch {
      // The failed head remains owned by the queue and will be retried by a
      // later record/flush call. Do not re-enqueue it here: a concurrent
      // flush may already have delivered it successfully.
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
    try {
      while (this.queue.length > 0) {
        const next = this.queue[0];
        this.inFlight = next;
        try {
          await this.post(next);
        } finally {
          this.inFlight = null;
        }
        // Only the flush that owns this head may remove it. Other records can
        // append concurrently, but they cannot shift the in-flight event.
        if (this.queue[0] === next) {
          this.queue.shift();
        } else {
          const index = this.queue.indexOf(next);
          if (index >= 0) {
            this.queue.splice(index, 1);
          }
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
    const fetcher = this.options.fetchImpl ?? fetch;
    const response = await fetcher(`${new URL(this.options.launcherOrigin).origin}/api/launcher/runtime-scene/events`, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        "X-Vibelution-Control-Token": this.options.controlToken
      },
      body: JSON.stringify(electronEventPayload(event))
    });
    if (!response.ok) {
      throw new Error(`runtime scene event rejected: ${response.status}`);
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
