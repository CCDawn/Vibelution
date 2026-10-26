import { resolve } from "node:path";

export type BackgroundWorkbenchRetirementResult = "closed" | "superseded";
export type BackgroundWorkbenchRetirementStatus = "pending" | BackgroundWorkbenchRetirementResult;

export type BackgroundWorkbenchRetirementInput = {
  workspaceRoot: string;
  requestId: string;
  /** The already captured, bounded exact-Job retirement; never discover a new PID here. */
  retireCaptured: () => Promise<boolean>;
  /** Probe only the original listener. Probe failure is not evidence of closure. */
  portClosed: () => Promise<boolean>;
  /** Caller-owned lifecycle/epoch fence; false confirms supersession, throws mean temporarily unavailable. */
  isCurrent: () => boolean;
  /** Must check the caller's epoch at the actual state write; false means superseded. */
  commitClosed: () => Promise<boolean>;
  retryIntervalMs?: number;
  delay?: (milliseconds: number) => Promise<void>;
};

export type BackgroundWorkbenchRetirementOwner = {
  readonly requestId: string;
  readonly status: BackgroundWorkbenchRetirementStatus;
  readonly completion: Promise<BackgroundWorkbenchRetirementResult>;
};

const owners = new Map<string, BackgroundWorkbenchRetirementOwner>();
const delay = (milliseconds: number): Promise<void> => new Promise((done) => { setTimeout(done, milliseconds); });

// Match workbenchJob's process-local project key without importing native/process code.
function projectKey(workspaceRoot: string): string {
  return resolve(workspaceRoot).replaceAll("\\", "/").toLowerCase();
}

export function getBackgroundWorkbenchRetirement(workspaceRoot: string): BackgroundWorkbenchRetirementOwner | undefined {
  return owners.get(projectKey(workspaceRoot));
}

export function hasBackgroundWorkbenchRetirement(workspaceRoot: string): boolean {
  return getBackgroundWorkbenchRetirement(workspaceRoot)?.status === "pending";
}

export async function waitForBackgroundWorkbenchRetirement(
  workspaceRoot: string
): Promise<BackgroundWorkbenchRetirementResult | undefined> {
  return await getBackgroundWorkbenchRetirement(workspaceRoot)?.completion;
}

/**
 * Keep retirement alive beyond the window-close deadline. One process-local owner
 * holds the trusted closures for each project; repeated requests join that owner.
 * This coordinates evidence only: the caller retains Job and state-write authority.
 */
export function startBackgroundWorkbenchRetirement(input: BackgroundWorkbenchRetirementInput): BackgroundWorkbenchRetirementOwner {
  const key = projectKey(input.workspaceRoot);
  const existing = owners.get(key);
  if (existing?.status === "pending") return existing;
  const configuredInterval = input.retryIntervalMs ?? 250;
  if (!Number.isFinite(configuredInterval) || configuredInterval <= 0) {
    throw new RangeError("background retirement retry interval must be positive and finite");
  }
  const retryInterval = Math.max(25, Math.min(10_000, configuredInterval));
  let status: BackgroundWorkbenchRetirementStatus = "pending";
  let complete!: (result: BackgroundWorkbenchRetirementResult) => void;
  const completion = new Promise<BackgroundWorkbenchRetirementResult>((done) => { complete = done; });
  const owner: BackgroundWorkbenchRetirementOwner = Object.freeze({
    requestId: input.requestId,
    get status() { return status; },
    completion
  });
  owners.set(key, owner);

  void retireUntilConfirmed(input, retryInterval).then((result) => {
    status = result;
    complete(result);
  }).finally(() => {
    // Completion observers may already have installed a new owner for this root.
    if (owners.get(key) === owner) owners.delete(key);
  });
  return owner;
}

async function retireUntilConfirmed(
  input: BackgroundWorkbenchRetirementInput,
  retryInterval: number
): Promise<BackgroundWorkbenchRetirementResult> {
  let retired = false;
  const current = (): boolean | undefined => {
    try { return input.isCurrent(); } catch { return undefined; }
  };
  for (;;) {
    const beforeRetirement = current();
    if (beforeRetirement === false) return "superseded";
    try {
      // An unreadable fence is not authority to mutate or proof of supersession.
      if (beforeRetirement === true) {
        if (!retired) retired = await input.retireCaptured();
        const afterRetirement = current();
        if (afterRetirement === false) return "superseded";
        if (afterRetirement === true && retired) {
          const closed = await input.portClosed();
          const afterProbe = current();
          if (afterProbe === false) return "superseded";
          if (afterProbe === true && closed) return await input.commitClosed() ? "closed" : "superseded";
        }
      }
    } catch {
      // Native/probe/write errors keep the owner pending, never manufacture closed.
    }
    try {
      await (input.delay ?? delay)(retryInterval);
    } catch {
      // A faulty injected scheduler must not drop the owner or cause a busy loop.
      await delay(retryInterval);
    }
  }
}
