export type DesktopSessionMirrorResult = {
  desktopSessionId: string;
  revision: number;
};

type DesktopSessionMirrorMutationKind = "window" | "heartbeat" | "close";
type MirrorErrorHandler = (error: unknown) => void;

/**
 * Keeps the legacy Python desktop-session projection ordered without making it
 * authoritative for Electron's in-process window/session state.
 */
export class DesktopSessionMirrorQueue {
  private tail: Promise<void> = Promise.resolve();
  private revision = 0;

  constructor(private readonly onError: MirrorErrorHandler = () => undefined) {}

  currentRevision(): number {
    return this.revision;
  }

  register(operation: () => Promise<DesktopSessionMirrorResult>): Promise<void> {
    return this.enqueue(async () => {
      this.revision = validRevision((await operation()).revision);
    });
  }

  mutate(
    _kind: DesktopSessionMirrorMutationKind,
    operation: (revision: number) => Promise<DesktopSessionMirrorResult>
  ): Promise<void> {
    return this.enqueue(async () => {
      let expectedRevision = this.revision > 0 ? this.revision : 1;
      try {
        this.revision = validRevision((await operation(expectedRevision)).revision);
      } catch (error: unknown) {
        const actualRevision = conflictRevision(error);
        if (actualRevision <= 0 || actualRevision === expectedRevision) {
          throw error;
        }
        this.revision = actualRevision;
        expectedRevision = actualRevision;
        this.revision = validRevision((await operation(expectedRevision)).revision);
      }
    });
  }

  private enqueue(operation: () => Promise<void>): Promise<void> {
    const result = this.tail.then(operation).catch((error: unknown) => {
      this.onError(error);
    });
    this.tail = result;
    return result;
  }
}

function conflictRevision(error: unknown): number {
  if (typeof error !== "object" || error === null || !("actualRevision" in error)) {
    return 0;
  }
  const revision = Number((error as { actualRevision?: unknown }).actualRevision ?? 0);
  return Number.isInteger(revision) && revision > 0 ? revision : 0;
}

function validRevision(value: number): number {
  if (!Number.isInteger(value) || value <= 0) {
    throw new Error(`invalid desktop session mirror revision: ${value}`);
  }
  return value;
}
