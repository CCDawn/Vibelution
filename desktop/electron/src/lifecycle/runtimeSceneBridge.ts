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

  constructor(private readonly options: RuntimeSceneBridgeOptions) {}

  async record(event: RuntimeSceneElectronEvent): Promise<void> {
    const bounded = this.bound(event);
    try {
      await this.post(bounded);
      await this.flush();
    } catch {
      this.queue.push(bounded);
      while (this.queue.length > this.options.maxBufferedEvents) {
        this.queue.shift();
      }
    }
  }

  async flush(): Promise<void> {
    while (this.queue.length > 0) {
      const next = this.queue[0];
      await this.post(next);
      this.queue.shift();
    }
  }

  bufferedCount(): number {
    return this.queue.length;
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
