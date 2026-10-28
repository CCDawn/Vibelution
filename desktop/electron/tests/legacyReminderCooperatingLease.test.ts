import { createHash, randomBytes } from "node:crypto";
import { spawn } from "node:child_process";
import { createInterface } from "node:readline";
import { mkdirSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { describe, expect, it, vi } from "vitest";

vi.mock("../src/process/workbenchJob.js", async () => {
  const { createRequire } = await import("node:module");
  return { loadWorkbenchJobNative: () => createRequire(import.meta.url)(process.env.VIBELUTION_MUTEX_TEST_ADDON!) };
});
import { LegacyReminderCoordinator, LegacyReminderDailyIntentStores } from "../src/notifications/legacyReminderCoordinator.js";
import { tryAcquireReminderSourceMutex } from "../src/notifications/reminderSourceMutex.js";
import { LegacyReminderEvidenceIndex, inventoryLegacyReminderIntents, reconcileLegacyReminderEvidence } from "../src/notifications/legacyReminderEvidence.js";

describe.skipIf(!process.env.VIBELUTION_MUTEX_TEST_ADDON)("cooperating legacy source lease", () => {
  it("drains settlement and excludes the real Python affairs writer until release", async () => {
    const root = mkdtempSync(join(tmpdir(), "legacy-source-lease-"));
    const profile = join(root, "user"), temp = join(root, "tmp");
    for (const path of [profile, join(profile, "Local"), join(profile, "Roaming"), temp]) mkdirSync(path, { recursive: true });
    const code = `
import json, os, sys
from pathlib import Path
from core.agent_plugins.personal_affairs.service import PersonalAffairsService, PersonalAffairsError
from core.assistant_runtime.initial_migration_binding import _digest, _directory
root=Path(os.environ['TEST_ROOT']) / 'project'
agents={'pa':{'agentId':'pa'},'other':{'agentId':'other'}}
service=PersonalAffairsService(root, agent_loader=lambda name, **kw: agents[name], source_mutex_guard=lambda agent: agent['agentId']=='pa')
service.add_item('pa',kind='todo',title='initial')
ledger=service.store._path('pa','affairs/items.jsonl')
key=_digest({'path':str(ledger).casefold(),'parent':_directory(ledger.parent),'agentId':'pa'})
print(json.dumps({'key':key}),flush=True)
for line in sys.stdin:
 try:
  name=json.loads(line)['agent']
  row=service.add_item(name,kind='todo',title='fixture')
  print(json.dumps({'state':'written','id':row['itemId']}),flush=True)
 except PersonalAffairsError:
  print(json.dumps({'state':'busy'}),flush=True)
`;
    const env = Object.fromEntries(Object.entries(process.env).filter(([key]) => !key.toUpperCase().startsWith("VIBELUTION_")));
    Object.assign(env, { TEST_ROOT: root, USERPROFILE: profile, HOME: profile, LOCALAPPDATA: join(profile, "Local"),
      APPDATA: join(profile, "Roaming"), TEMP: temp, TMP: temp, PYTHONDONTWRITEBYTECODE: "1", PYTHONIOENCODING: "utf-8" });
    const child = spawn("python", ["-B", "-c", code], { cwd: resolve(process.cwd(), "../.."), env, windowsHide: true, stdio: "pipe" });
    const lines = createInterface({ input: child.stdout! });
    const queue: string[] = [], waiters: Array<(value: string) => void> = [];
    lines.on("line", line => { const waiter = waiters.shift(); if (waiter) waiter(line); else queue.push(line); });
    const next = () => new Promise<string>(resolve => { const line = queue.shift(); if (line !== undefined) resolve(line); else waiters.push(resolve); });
    let stderr = ""; child.stderr!.on("data", value => { stderr += String(value); });
    try {
      const { key: ledgerKey } = JSON.parse(await next());
      expect(ledgerKey).toMatch(/^[a-f0-9]{64}$/);
      const sourceKey = "a".repeat(64), otherSource = "c".repeat(64), globalKey = randomBytes(32).toString("hex");
      let changed = false;
      const binding = () => ({ ledgerKey, verify: () => { if (changed) throw new Error("source changed"); } });
      const authority = { indexDirectory: join(root, "index"), oldIntentDirectory: join(root, "old"),
        tryAcquireGlobal: () => tryAcquireReminderSourceMutex({ ledgerKey: globalKey, verify: () => {} }),
        inventoryReceipts: async () => ({ schemaVersion: 1, records: [], senders: 0 }), verifyRecovery: () => {} };
      const probe = tryAcquireReminderSourceMutex(binding());
      expect(probe).not.toBeNull();
      const global = authority.tryAcquireGlobal();
      expect(global).not.toBeNull();
      const verify = () => { probe!.check(); global!.check(); };
      const idx = new LegacyReminderEvidenceIndex(authority.indexDirectory, verify);
      reconcileLegacyReminderEvidence(idx.inventory(), inventoryLegacyReminderIntents(authority.oldIntentDirectory, verify), await authority.inventoryReceipts());
      global!.release(); probe!.release();
      const eventId = "affair-reminder:fixture:20261028";
      const eventKey = "legacy:" + createHash("sha256").update(JSON.stringify([sourceKey, eventId]), "ascii").digest("hex");
      let finishSettlement!: () => void;
      const attempts = { reserve: vi.fn(async () => ({ schemaVersion: 1, eventKey, state: "reserved", attemptToken: "d".repeat(64) })),
        settle: vi.fn(() => new Promise(resolve => { finishSettlement = () => resolve({ schemaVersion: 1,
          eventKey, state: "submitted", channel: "system_notification" }); })) };
      const coordinator = new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory),
        attempts, () => new Date("2026-10-28T01:00:00Z"), binding, authority);
      const occupied = tryAcquireReminderSourceMutex(binding());
      expect(occupied).not.toBeNull();
      expect(await coordinator.acquireCooperatingSourceLease(sourceKey)).toBeNull();
      occupied!.release();
      const send = vi.fn(async () => ({ delivered: "system_notification" as const }));
      const request = { sourceKey, eventId, isCurrent: () => true, send };
      const pending = coordinator.dispatch(request);
      try { await vi.waitFor(() => expect(finishSettlement).toBeTypeOf("function")); }
      catch { throw new Error("dispatch did not reach settlement: " + JSON.stringify(await pending)); }
      let held = false;
      const acquiring = coordinator.acquireCooperatingSourceLease(sourceKey).then(value => { held = true; return value; });
      expect(await coordinator.dispatch(request)).toEqual({ delivered: "source_busy" });
      expect(held).toBe(false);
      finishSettlement();
      expect(await pending).toEqual({ delivered: "system_notification" });
      const lease = await acquiring;
      expect(await lease?.check()).toEqual({ schemaVersion: 1, ledgerKey, localCoordinatorDrained: true,
        cooperatingMutexHeld: true, priorOutcomes: "unknown", unmanagedSenders: "unknown", readyForCutover: false });
      const write = async (agent: string) => { child.stdin!.write(JSON.stringify({ agent }) + "\n"); return JSON.parse(await next()); };
      expect((await write("pa")).state, stderr).toBe("busy");
      expect((await write("other")).state).toBe("written");
      expect(await coordinator.dispatch({ ...request, sourceKey: otherSource, eventId: "affair-reminder:other:20261028" }))
        .toEqual({ delivered: "source_busy" });
      changed = true;
      await expect(lease!.check()).rejects.toThrow("source changed");
      changed = false;
      await lease!.release();
      await expect(lease!.check()).rejects.toThrow("LEGACY_REMINDER_LEASE_RELEASED");
      expect((await write("pa")).state).toBe("written");
    } finally {
      child.stdin?.end();
      if (child.exitCode === null) await new Promise<void>(resolve => { child.once("exit", () => resolve()); });
      lines.close();
      rmSync(root, { recursive: true, force: true });
    }
  }, 20000);
});
