import { describe, expect, it } from "vitest";

import { DesktopSessionMirrorQueue } from "../src/lifecycle/desktopSessionMirrorQueue.js";

describe("DesktopSessionMirrorQueue", () => {
  it("serializes register and mutations while advancing the mirror revision from remote responses", async () => {
    const operations: string[] = [];
    const mirror = new DesktopSessionMirrorQueue();

    const registration = mirror.register(async () => {
      operations.push("register");
      return { desktopSessionId: "desktop-1", revision: 4 };
    });
    const windowUpdate = mirror.mutate("window", async (revision) => {
      operations.push(`window:${revision}`);
      return { desktopSessionId: "desktop-1", revision: revision + 1 };
    });
    const heartbeat = mirror.mutate("heartbeat", async (revision) => {
      operations.push(`heartbeat:${revision}`);
      return { desktopSessionId: "desktop-1", revision: revision + 1 };
    });

    await Promise.all([registration, windowUpdate, heartbeat]);

    expect(operations).toEqual(["register", "window:4", "heartbeat:5"]);
    expect(mirror.currentRevision()).toBe(6);
  });

  it("recovers a stale mirror revision from one conflict and retries the mutation once", async () => {
    const attempts: number[] = [];
    const mirror = new DesktopSessionMirrorQueue();

    await mirror.mutate("window", async (revision) => {
      attempts.push(revision);
      if (attempts.length === 1) {
        throw Object.assign(new Error("revision conflict"), { actualRevision: 7 });
      }
      return { desktopSessionId: "desktop-1", revision: revision + 1 };
    });

    expect(attempts).toEqual([1, 7]);
    expect(mirror.currentRevision()).toBe(8);
  });

  it("keeps later mirror work running after a best-effort request fails", async () => {
    const errors: string[] = [];
    const operations: string[] = [];
    const mirror = new DesktopSessionMirrorQueue((error) => errors.push(String(error)));

    const failed = mirror.register(async () => {
      operations.push("register");
      throw new Error("offline");
    });
    const recovered = mirror.mutate("heartbeat", async (revision) => {
      operations.push(`heartbeat:${revision}`);
      return { desktopSessionId: "desktop-1", revision: 2 };
    });

    await Promise.all([failed, recovered]);

    expect(operations).toEqual(["register", "heartbeat:1"]);
    expect(errors).toEqual(["Error: offline"]);
    expect(mirror.currentRevision()).toBe(2);
  });
});
