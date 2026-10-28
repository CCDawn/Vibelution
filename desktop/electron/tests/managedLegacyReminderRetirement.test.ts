import { expect, it, vi } from "vitest";
import { startManagedLegacyReminderRetirement } from "../src/notifications/managedLegacyReminderRetirement.js";
import type { ElectronWindowProvider } from "../src/windows/electronWindowProvider.js";

function fixture() {
  const rows: Array<{ kind: string; instanceId: string | null; windowId: number; rendererProcessId: number; ready: boolean }> = [
    { kind: "instance", instanceId: "target", windowId: 1, rendererProcessId: 101, ready: true },
    { kind: "instance", instanceId: "other", windowId: 2, rendererProcessId: 102, ready: true },
  ];
  const closed = new Set<number>();
  const close = vi.fn(async () => { throw new Error("migration must not close windows"); });
  const capture = vi.fn((row: typeof rows[number], options: unknown) => ({ instanceId: row.instanceId, windowId: row.windowId,
    isClosed: () => closed.has(row.windowId), close, options }));
  const provider = { completeWorkbenchWindowInventory: () => rows.filter(row => !closed.has(row.windowId)),
    captureWorkbenchWindowRetirement: capture, hasPendingUserWorkbenchClose: () => false } as unknown as ElectronWindowProvider;
  const job = Object.assign(vi.fn(async () => true), { isCurrent: () => true, release: () => {}, pid: 101 });
  const admission = { root: "fixture", drain: vi.fn(async () => {}), release: () => {} };
  const drainIngress = vi.fn(async () => {});
  let closeSettled = true, valid = true;
  const owner = startManagedLegacyReminderRetirement({ provider, instanceIds: ["target"], jobs: [job], admission,
    verifyBinding: () => { if (!valid) throw new Error("identity unavailable"); },
    verifyWindowCloseSettled: () => { if (!closeSettled) throw new Error("close still in progress"); },
    drainIngress, retryMs: 25 });
  return { rows, closed, close, capture, job, admission, drainIngress, owner,
    setCloseSettled: (value: boolean) => { closeSettled = value; }, setValid: (value: boolean) => { valid = value; } };
}

it("waits for user closure and its transaction ACK before draining or observing the captured Job", async () => {
  const f = fixture();
  expect(f.owner.waitingFor).toBe("window");
  expect(f.capture).toHaveBeenCalledOnce();
  expect(f.capture.mock.calls[0][1]).toEqual({ naturalOnly: true });
  expect(f.close).not.toHaveBeenCalled();
  expect(f.job).not.toHaveBeenCalled();
  f.setCloseSettled(false);
  f.closed.add(1); // Independent user-driven close; not initiated by migration.
  await vi.waitFor(() => expect(f.owner.waitingFor).toBe("close_transaction"));
  expect(f.admission.drain).not.toHaveBeenCalled();
  expect(f.job).not.toHaveBeenCalled();
  f.setCloseSettled(true);
  expect(await f.owner.completion).toEqual({ state: "managed_drained", unmanagedSenders: "unknown", readyForCutover: false });
  expect(f.owner.waitingFor).toBeNull();
  expect(f.close).not.toHaveBeenCalled();
  expect(f.job).toHaveBeenCalledOnce();
  expect(f.closed.has(2)).toBe(false);
});

it.each(["admission", "ingress"])("keeps a replacement window and pending work safe during %s drain", async stage => {
  const f = fixture();
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  if (stage === "admission") f.admission.drain.mockImplementationOnce(() => pending);
  else f.drainIngress.mockImplementationOnce(() => pending);
  f.closed.add(1);
  if (stage === "admission") await vi.waitFor(() => expect(f.admission.drain).toHaveBeenCalled());
  else await vi.waitFor(() => expect(f.drainIngress).toHaveBeenCalled());
  f.rows.push({ kind: "instance", instanceId: "target", windowId: 3, rendererProcessId: 103, ready: true });
  release();
  await vi.waitFor(() => expect(f.owner.waitingFor).toBe("unknown"));
  expect(f.capture).toHaveBeenCalledOnce();
  expect(f.close).not.toHaveBeenCalled();
  expect(f.job).not.toHaveBeenCalled();
  f.owner.dispose();
  expect((await f.owner.completion).state).toBe("pending");
});

it("rechecks close transactions that begin during the ingress drain", async () => {
  const f = fixture();
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  f.drainIngress.mockImplementationOnce(() => pending);
  f.closed.add(1);
  await vi.waitFor(() => expect(f.drainIngress).toHaveBeenCalled());
  f.setCloseSettled(false); release();
  await vi.waitFor(() => expect(f.owner.waitingFor).toBe("close_transaction"));
  expect(f.job).not.toHaveBeenCalled();
  f.setCloseSettled(true);
  expect((await f.owner.completion).state).toBe("managed_drained");
});

it("leaves changed source identity pending without touching the original window or Job", async () => {
  const f = fixture();
  f.setValid(false); f.closed.add(1);
  await vi.waitFor(() => expect(f.owner.waitingFor).toBe("unknown"));
  expect(f.close).not.toHaveBeenCalled();
  expect(f.job).not.toHaveBeenCalled();
  f.owner.dispose();
});

it("does not certify a drain if an unattributed window appears during the final ingress wait", async () => {
  const f = fixture();
  let release!: () => void;
  const pending = new Promise<void>(resolve => { release = resolve; });
  f.drainIngress.mockResolvedValueOnce(undefined).mockImplementationOnce(() => pending);
  f.closed.add(1);
  await vi.waitFor(() => expect(f.drainIngress).toHaveBeenCalledTimes(2));
  f.rows.push({ kind: "unattributed", instanceId: null, windowId: 9, rendererProcessId: 109, ready: false });
  release();
  await vi.waitFor(() => expect(f.owner.waitingFor).toBe("unknown"));
  expect(f.owner.state).toBe("pending");
  expect(f.capture).toHaveBeenCalledOnce();
  expect(f.close).not.toHaveBeenCalled();
  f.owner.dispose();
});

it("does not establish a capture set after the first source identity check fails", async () => {
  let valid = false;
  const capture = vi.fn();
  const provider = { completeWorkbenchWindowInventory: () => [], captureWorkbenchWindowRetirement: capture,
    hasPendingUserWorkbenchClose: () => false } as unknown as ElectronWindowProvider;
  const job = Object.assign(vi.fn(async () => true), { isCurrent: () => true, release: () => {}, pid: 1 });
  const owner = startManagedLegacyReminderRetirement({ provider, instanceIds: ["target"], jobs: [job],
    admission: { root: "fixture", drain: async () => {}, release: () => {} },
    verifyBinding: () => { if (!valid) throw new Error("source unavailable"); },
    verifyWindowCloseSettled: () => {}, drainIngress: async () => {}, retryMs: 25 });
  valid = true;
  await new Promise(resolve => setTimeout(resolve, 100));
  expect(capture).not.toHaveBeenCalled();
  expect(job).not.toHaveBeenCalled();
  expect(owner.waitingFor).toBe("unknown");
  owner.dispose();
});

it("rejects a force-capable Job or missing transaction proof", () => {
  const provider = {} as ElectronWindowProvider;
  const base = { provider, instanceIds: ["target"], jobs: [Object.assign(async () => true, { isCurrent: () => true })],
    admission: { root: "fixture", drain: async () => {}, release: () => {} }, verifyBinding: () => {},
    verifyWindowCloseSettled: () => {}, drainIngress: async () => {} };
  expect(() => startManagedLegacyReminderRetirement(base as never)).toThrow("LEGACY_RETIREMENT_INVALID");
  expect(() => startManagedLegacyReminderRetirement({ ...base, jobs: [Object.assign(async () => true,
    { isCurrent: () => true, release: () => {}, pid: 1 })], verifyWindowCloseSettled: undefined } as never))
    .toThrow("LEGACY_RETIREMENT_INVALID");
});
