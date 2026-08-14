import type { ManagedWindowState } from "./windowProviderTypes.js";

export type InProcessDesktopSession = {
  desktopSessionId: string;
  revision: number;
  capabilities: string[];
  windows: Partial<Record<"launcher" | "workbench", ManagedWindowState>>;
  registered: boolean;
};

export type DesktopSessionRegistrationResult = {
  desktopSessionId: string;
  revision: number;
};

export class InProcessDesktopSessionStore {
  private session: InProcessDesktopSession | null = null;

  register(input: {
    desktopSessionId: string;
    capabilities: string[];
  }): DesktopSessionRegistrationResult {
    this.session = {
      desktopSessionId: input.desktopSessionId,
      revision: 1,
      capabilities: [...input.capabilities],
      windows: {},
      registered: true,
    };
    return { desktopSessionId: input.desktopSessionId, revision: 1 };
  }

  heartbeat(input: { desktopSessionId: string; revision: number }): DesktopSessionRegistrationResult {
    this.assertRegistered(input.desktopSessionId, input.revision);
    this.session!.revision += 1;
    return { desktopSessionId: this.session!.desktopSessionId, revision: this.session!.revision };
  }

  reportWindow(input: {
    desktopSessionId: string;
    role: "launcher" | "workbench";
    revision: number;
    state: ManagedWindowState;
  }): DesktopSessionRegistrationResult {
    this.assertRegistered(input.desktopSessionId, input.revision);
    this.session!.windows[input.role] = input.state;
    this.session!.revision += 1;
    return { desktopSessionId: this.session!.desktopSessionId, revision: this.session!.revision };
  }

  close(input: { desktopSessionId: string; revision: number }): DesktopSessionRegistrationResult {
    this.assertRegistered(input.desktopSessionId, input.revision);
    const result = { desktopSessionId: this.session!.desktopSessionId, revision: this.session!.revision + 1 };
    this.session = null;
    return result;
  }

  snapshot(): InProcessDesktopSession | null {
    return this.session;
  }

  private assertRegistered(desktopSessionId: string, revision: number): void {
    if (this.session === null) {
      throw new Error("in-process desktop session is not registered");
    }
    if (this.session.desktopSessionId !== desktopSessionId) {
      throw new Error("in-process desktop session identity mismatch");
    }
    if (revision !== this.session.revision) {
      throw new Error(
        `in-process desktop session revision conflict: expected ${revision}, actual ${this.session.revision}`
      );
    }
  }
}
