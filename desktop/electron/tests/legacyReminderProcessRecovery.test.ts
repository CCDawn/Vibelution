import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { buildSync } from "esbuild";
import { expect, it } from "vitest";

const addon = process.env.VIBELUTION_MUTEX_TEST_ADDON;
it.skipIf(!addon)("recovers an indexed unknown attempt after a real process restart", () => {
  const root = mkdtempSync(join(tmpdir(), "legacy-process-recovery-"));
  try {
    const coordinator = resolve("src/notifications/legacyReminderCoordinator.ts");
    const mutex = resolve("src/notifications/reminderSourceMutex.ts");
    const native = resolve("src/process/workbenchJob.ts");
    const script = join(root, "child.mjs");
    buildSync({ stdin: { resolveDir: process.cwd(), sourcefile: "fixture.ts", contents: `
      import { createHash } from 'node:crypto';
      import { createRequire } from 'node:module';
      import { readFileSync, writeFileSync, existsSync } from 'node:fs';
      import { join } from 'node:path';
      import { LegacyReminderCoordinator, LegacyReminderDailyIntentStores } from ${JSON.stringify(coordinator)};
      import { tryAcquireReminderSourceMutex } from ${JSON.stringify(mutex)};
      import { __setWorkbenchJobNativeForTests } from ${JSON.stringify(native)};
      __setWorkbenchJobNativeForTests(createRequire(import.meta.url)(process.env.FIXTURE_ADDON));
      const root=process.env.FIXTURE_ROOT, phase=process.env.FIXTURE_PHASE, ledger='b'.repeat(64), source='a'.repeat(64), token='c'.repeat(64);
      const path=join(root,'receipts.json'), records=existsSync(path)?JSON.parse(readFileSync(path,'utf8')):[];
      const key=id=>'legacy:'+createHash('sha256').update(JSON.stringify([source,id]),'ascii').digest('hex');
      const attempts={reserve:async r=>{if(r.eventId.includes(':old:')) process.exit(77);return {schemaVersion:1,eventKey:key(r.eventId),state:'reserved',attemptToken:token};},
        settle:async r=>{records.push({day:'20261028',eventKey:key(r.eventId),state:'submitted',channel:'system_notification',inflight:false});writeFileSync(path,JSON.stringify(records));return {schemaVersion:1,eventKey:key(r.eventId),state:'submitted',channel:'system_notification'};}};
      const authority={indexDirectory:join(root,'index'),oldIntentDirectory:join(root,'old'),
        tryAcquireGlobal:()=>tryAcquireReminderSourceMutex({ledgerKey:'d'.repeat(64),verify:()=>{}}),
        inventoryReceipts:async()=>({schemaVersion:1,records,senders:0}),verifyRecovery:()=>{}};
      const instance=new LegacyReminderCoordinator(new LegacyReminderDailyIntentStores(authority.oldIntentDirectory),attempts,()=>new Date('2026-10-28T01:00:00Z'),()=>({ledgerKey:ledger,verify:()=>{}}),authority);
      let sends=0; const request=id=>({sourceKey:source,eventId:'affair-reminder:'+id+':20261028',isCurrent:()=>true,send:async()=>{sends++;return {delivered:'system_notification'};}});
      const out=phase==='first'?[await instance.dispatch(request('old'))]:phase==='recover'?[await instance.dispatch(request('new')),await instance.recoverSource(source,()=>true),await instance.dispatch(request('old')),await instance.dispatch(request('new'))]:[await instance.dispatch(request('old')),await instance.dispatch(request('new'))];
      process.stdout.write(JSON.stringify({out,sends}));
    ` }, bundle: true, platform: "node", format: "esm", outfile: script, logLevel: "silent" });
    const run = (phase: string) => {
      const child = spawnSync(process.execPath, [script], { windowsHide: true, encoding: "utf8", timeout: 30000,
        env: { ...process.env, FIXTURE_ROOT: root, FIXTURE_ADDON: addon, FIXTURE_PHASE: phase } });
      if (phase === "first") { expect(child.status, child.stderr).toBe(77); return null; }
      expect(child.status, child.stderr).toBe(0);
      return JSON.parse(child.stdout);
    };
    run("first");
    expect(run("recover")).toEqual({ out: [{ delivered: "source_recovery_required" }, "recovered",
      { delivered: "attempt_pending" }, { delivered: "system_notification" }], sends: 1 });
    expect(run("restart")).toEqual({ out: [{ delivered: "attempt_pending" }, { delivered: "attempt_pending" }], sends: 0 });
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 30000);
