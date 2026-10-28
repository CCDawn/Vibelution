import { createHash } from "node:crypto";
import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, describe, expect, it, vi } from "vitest";
import { LegacyReminderCoordinator, LegacyReminderDailyIntentStores, LegacyReminderNegotiatedDocuments } from "../src/notifications/legacyReminderCoordinator.js";

const sourceKey = "a".repeat(64);
const eventId = "affair-reminder:fictional-item:20261028";
const token = "b".repeat(64);
const clock = () => new Date("2026-10-28T01:00:00Z");
const key = "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
const directories: string[] = [];
function directory() {
  const value = mkdtempSync(join(tmpdir(), "legacy-reminder-intent-"));
  directories.push(value);
  return value;
}
function api() {
  return {
    reserve: vi.fn().mockResolvedValue({ schemaVersion: 1, eventKey: key, state: "reserved", attemptToken: token }),
    settle: vi.fn().mockResolvedValue({ schemaVersion: 1, eventKey: key, state: "submitted", channel: "system_notification" }),
    abandon: vi.fn().mockResolvedValue({ schemaVersion: 1, eventKey: key, state: "abandoned" }),
  };
}
afterEach(() => { for (const path of directories.splice(0)) rmSync(path, { recursive: true, force: true }); });

describe("legacy reminder attempt coordination", () => {
  it("uses the same stable event key as the Python owner and keeps document negotiation sticky", () => {
    expect(key).toBe("legacy:f1889ea2d4f47cf2288166d5ff33ba0a7fd8a99c4f3d89aab03d262ad051c623");
    const documents = new LegacyReminderNegotiatedDocuments(), document = {}, replacement = {};
    expect(documents.has(document)).toBe(false);
    expect(documents.begin(document)).toBe(true);
    expect(documents.has(document)).toBe(true);
    expect(documents.isCommitted(document)).toBe(false);
    documents.commit(document);
    expect(documents.isCommitted(document)).toBe(true);
    expect(documents.begin(document)).toBe(false);
    expect(documents.has(replacement)).toBe(false);
  });
  it("admits one competing window and persists the event intent", async () => {
    const root = directory(), attempts = api();
    let release!: (value: unknown) => void;
    attempts.reserve.mockImplementationOnce(() => new Promise(resolve => { release = resolve; }));
    const intents = new LegacyReminderDailyIntentStores(root);
    const coordinator = new LegacyReminderCoordinator(intents, attempts, clock);
    const send = vi.fn().mockResolvedValue({ delivered: "system_notification" });
    const request = { sourceKey, eventId, isCurrent: () => true, send };
    const first = coordinator.dispatch(request);
    await vi.waitFor(() => expect(attempts.reserve).toHaveBeenCalledTimes(1));
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    release({ schemaVersion: 1, eventKey: key, state: "reserved", attemptToken: token });
    expect(await first).toEqual({ delivered: "system_notification" });
    expect(send).toHaveBeenCalledTimes(1);
    expect(attempts.abandon).not.toHaveBeenCalled();
    const restarted = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(root), attempts, clock);
    expect(await restarted.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(attempts.reserve).toHaveBeenCalledTimes(1);
  });

  it("never retries an unknown reserve outcome even after main restarts", async () => {
    const root = directory(), attempts = api(), send = vi.fn();
    attempts.reserve.mockRejectedValueOnce(new Error("unknown"));
    const request = { sourceKey, eventId, isCurrent: () => true, send };
    const first = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(root), attempts, clock);
    expect(await first.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    const second = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(root), attempts, clock);
    expect(await second.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(attempts.reserve).toHaveBeenCalledTimes(1);
    expect(send).not.toHaveBeenCalled();
    expect(attempts.abandon).not.toHaveBeenCalled();
  });

  it("does not send after source authority changes or a reservation is invalid", async () => {
    const attempts = api(), root = directory(), send = vi.fn(), current = vi.fn().mockReturnValueOnce(true).mockReturnValueOnce(false);
    const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(root), attempts, clock);
    expect(await coordinator.dispatch({ sourceKey, eventId, isCurrent: current, send })).toEqual({ delivered: "attempt_pending" });
    expect(attempts.reserve).not.toHaveBeenCalled();
    expect(send).not.toHaveBeenCalled();
    expect(await coordinator.dispatch({ sourceKey, eventId, isCurrent: () => true, send })).toEqual({ delivered: "attempt_pending" });
  });

  it("never replays after a send with an unknown settlement", async () => {
    const attempts = api(), send = vi.fn().mockResolvedValue({ delivered: "system_notification" });
    attempts.settle.mockRejectedValueOnce(new Error("unknown"));
    const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(directory()), attempts, clock);
    const request = { sourceKey, eventId, isCurrent: () => true, send };
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(send).toHaveBeenCalledTimes(1);
    expect(attempts.abandon).toHaveBeenCalledExactlyOnceWith({ sourceKey, eventId, attemptToken: token });
  });
  it("closes admission synchronously and drains an in-flight send and settlement", async () => {
    const attempts = api();
    let releaseSend!: () => void;
    let releaseSettlement!: () => void;
    const send = vi.fn(() => new Promise<{ delivered: "system_notification" }>(resolve => {
      releaseSend = () => resolve({ delivered: "system_notification" });
    }));
    attempts.settle.mockImplementationOnce(() => new Promise(resolve => {
      releaseSettlement = () => resolve({ schemaVersion: 1, eventKey: key, state: "submitted", channel: "system_notification" });
    }));
    const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(directory()), attempts, clock);
    const request = { sourceKey, eventId, isCurrent: () => true, send };
    const first = coordinator.dispatch(request);
    await vi.waitFor(() => expect(send).toHaveBeenCalledOnce());
    let drained = false;
    const stopped = coordinator.stopAndDrain().then(() => { drained = true; });
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(drained).toBe(false);
    releaseSend();
    await vi.waitFor(() => expect(attempts.settle).toHaveBeenCalledOnce());
    expect(drained).toBe(false);
    releaseSettlement();
    expect(await first).toEqual({ delivered: "system_notification" });
    await stopped;
    expect(drained).toBe(true);
    expect(await coordinator.dispatch(request)).toEqual({ delivered: "attempt_pending" });
    expect(send).toHaveBeenCalledOnce();
  });
  it("rotates the durable intent namespace by UTC day without deleting the old day", async () => {
    const root = directory();
    let now = new Date("2026-10-28T01:00:00Z");
    const attempts = {
      reserve: vi.fn(async (request: { sourceKey: string; eventId: string }) => ({ schemaVersion: 1,
        eventKey: "legacy:" + createHash("sha256").update(JSON.stringify([request.sourceKey, request.eventId]), "ascii").digest("hex"),
        state: "reserved", attemptToken: token })),
      settle: vi.fn(async (request: { sourceKey: string; eventId: string }) => ({ schemaVersion: 1,
        eventKey: "legacy:" + createHash("sha256").update(JSON.stringify([request.sourceKey, request.eventId]), "ascii").digest("hex"),
        state: "submitted", channel: "system_notification" })),
    };
    const send = vi.fn().mockResolvedValue({ delivered: "system_notification" });
    const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(root), attempts, () => now);
    const run = (id: string) => coordinator.dispatch({ sourceKey, eventId: id, isCurrent: () => true, send });
    expect(await run(eventId)).toEqual({ delivered: "system_notification" });
    now = new Date("2026-10-29T01:00:00Z");
    expect(await run("affair-reminder:fictional-item:20261029")).toEqual({ delivered: "system_notification" });
    expect(existsSync(join(root, "20261028"))).toBe(true);
    expect(existsSync(join(root, "20261029"))).toBe(true);
    now = new Date("2026-10-28T01:00:00Z");
    expect(await run(eventId)).toEqual({ delivered: "attempt_pending" });
    expect(send).toHaveBeenCalledTimes(2);
  });
});
