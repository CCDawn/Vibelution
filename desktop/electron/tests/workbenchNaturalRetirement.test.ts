import { describe, expect, it, vi } from "vitest";
import { beginNaturalWorkbenchShutdown } from "../src/process/workbenchBackend.js";
import type { WorkbenchNaturalJobRetirement } from "../src/process/workbenchJob.js";

function fixture() {
  let exited = false;
  const job = Object.assign(vi.fn(async () => exited), { pid: 1234, isCurrent: () => !exited, release: vi.fn() }) as WorkbenchNaturalJobRetirement;
  const shutdown = vi.fn(async () => ({ requested: false, completed: false, status: 409, reason: "active" }));
  const verifyBinding = vi.fn(() => undefined);
  const owner = beginNaturalWorkbenchShutdown({ job, port: 12345, controlToken: "private-test-token", verifyBinding, shutdown });
  return { owner, job, shutdown, verifyBinding, exit: () => { exited = true; } };
}

describe("natural workbench shutdown", () => {
  it("leaves active work running and retries only an explicit 409", async () => {
    const f = fixture();
    expect(await f.owner.observe()).toBe("pending");
    expect(await f.owner.observe()).toBe("pending");
    expect(f.shutdown).toHaveBeenCalledTimes(2);
    expect(f.shutdown.mock.calls[0][0]).toMatchObject({ backendPid: 1234, interruptActiveWork: false, healthVerified: true });
    f.exit();
    expect(await f.owner.observe()).toBe("drained");
    expect(f.shutdown).toHaveBeenCalledTimes(2);
  });

  it("never resends an unconfirmed shutdown and retains the original Job", async () => {
    const f = fixture();
    f.shutdown.mockResolvedValue({ requested: false, completed: false, reason: "lost response" } as never);
    expect(await f.owner.observe()).toBe("pending");
    expect(await f.owner.observe()).toBe("pending");
    expect(f.shutdown).toHaveBeenCalledOnce();
    f.exit();
    expect(await f.owner.observe()).toBe("drained");
    expect(f.job.release).not.toHaveBeenCalled();
  });

  it("keeps an unknown source binding pending without requesting shutdown", async () => {
    const f = fixture();
    f.verifyBinding.mockImplementation(() => { throw new Error("binding changed"); });
    expect(await f.owner.observe()).toBe("pending");
    expect(f.shutdown).not.toHaveBeenCalled();
  });
});
