import { spawnSync } from "node:child_process";
import { existsSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { buildSync } from "esbuild";
import { expect, it } from "vitest";

const addon = process.env.VIBELUTION_MUTEX_TEST_ADDON;
const pythonw = process.env.VIBELUTION_TEST_PYTHONW;
const electron = resolve("node_modules/electron/dist/electron.exe");
it.skipIf(!addon || !pythonw || !existsSync(electron))("waits for an existing window's user close and ACK while blocking new windows", () => {
  const root = realpathSync.native(mkdtempSync(join(tmpdir(), "managed-reminder-retire-")));
  try {
    writeFileSync(join(root, "package.json"), JSON.stringify({ name: "managed-retire-fixture", version: "1.0.0", type: "module", main: "main.mjs" }));
    const provider = resolve("src/windows/electronWindowProvider.ts"), job = resolve("src/process/workbenchJob.ts");
    const admission = resolve("src/lifecycle/projectAdmission.ts"), retirement = resolve("src/notifications/managedLegacyReminderRetirement.ts");
    buildSync({ stdin: { resolveDir: process.cwd(), sourcefile: "fixture.ts", contents: `
      import {app,BrowserWindow} from 'electron'; import {createServer} from 'node:http'; import {createRequire} from 'node:module';
      import {statSync} from 'node:fs'; import {join} from 'node:path'; import assert from 'node:assert/strict';
      import {ElectronWindowProvider} from ${JSON.stringify(provider)};
      import {__setWorkbenchJobNativeForTests,spawnTrackedWorkbenchProcess,captureTrackedWorkbenchJobNaturalRetirement} from ${JSON.stringify(job)};
      import {ProjectAdmission} from ${JSON.stringify(admission)};
      import {startManagedLegacyReminderRetirement} from ${JSON.stringify(retirement)};
      const root=process.env.FIXTURE_ROOT; app.setPath('userData',join(root,'electron-data'));app.disableHardwareAcceleration();app.on('window-all-closed',()=>{});
      app.whenReady().then(async()=>{
        const native=createRequire(import.meta.url)(process.env.FIXTURE_ADDON); __setWorkbenchJobNativeForTests(native);
        const server=createServer((_req,res)=>res.end('<html><body>fixture</body></html>'));
        await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve)); const origin='http://127.0.0.1:'+server.address().port;
        const admission=new ProjectAdmission(), paths={schemaVersion:1,desktopBundleRoot:root,resourcesRoot:root,workspaceRoot:root,userDataRoot:root};
        let closing=false, releaseAck; const ack=new Promise(resolve=>releaseAck=resolve); const windows=[];
        const provider=new ElectronWindowProvider(paths,origin,origin,{createWorkbenchWindow:()=>{const w=new BrowserWindow({show:false});windows.push(w);return w;},
          listAllWindows:()=>BrowserWindow.getAllWindows(),assertInstanceOpenAllowed:()=>admission.assertOpen(root),
          onInstanceCloseRequest:async(id)=>{closing=true;await provider.closeInstanceWorkbench(id);await ack;closing=false;}});
        await provider.openOrFocusInstanceWorkbench({instanceId:'target',url:origin+'/target',present:false});
        const spawned=spawnTrackedWorkbenchProcess(root,{executable:process.env.FIXTURE_PYTHONW,arguments:['-c','import time; time.sleep(3)'],cwd:root,
          env:{...process.env},stdoutPath:join(root,'child-out.log'),stderrPath:join(root,'child-err.log'),containDescendants:true});
        const captured=captureTrackedWorkbenchJobNaturalRetirement(root,spawned.pid);assert.ok(captured);
        const seal=admission.seal(root), id=statSync(root,{bigint:true});let held=true;
        const operation=startManagedLegacyReminderRetirement({provider,instanceIds:['target'],jobs:[captured],admission:seal,
          verifyBinding:()=>{const current=statSync(root,{bigint:true});if(!held||current.dev!==id.dev||current.ino!==id.ino)throw Error('stale');},
          verifyWindowCloseSettled:()=>{if(closing)throw Error('close ACK pending');},drainIngress:async()=>{},retryMs:25});
        await new Promise(r=>setTimeout(r,200)); assert.equal(operation.waitingFor,'window'); assert.equal(windows[0].isDestroyed(),false);
        await assert.rejects(provider.openOrFocusInstanceWorkbench({instanceId:'other',url:origin+'/other',present:false}));
        windows[0].close(); // Simulate the existing user's close gesture.
        let deadline=Date.now()+4000;while(!windows[0].isDestroyed()&&Date.now()<deadline)await new Promise(r=>setTimeout(r,20));
        assert.equal(windows[0].isDestroyed(),true); assert.equal(closing,true);assert.equal(provider.hasPendingUserWorkbenchClose('target'),true);
        while(operation.waitingFor!=='close_transaction'&&Date.now()<deadline)await new Promise(r=>setTimeout(r,20));
        assert.equal(operation.waitingFor,'close_transaction'); assert.equal(captured.isCurrent(),true);
        releaseAck();const result=await operation.completion;
        assert.equal(result.state,'managed_drained');assert.equal(result.readyForCutover,false);
        held=false;seal.release();server.closeAllConnections();await new Promise(resolve=>server.close(resolve));
        process.stdout.write(JSON.stringify(result));app.exit(0);
      }).catch(error=>{process.stderr.write(String(error&&error.stack||error));app.exit(1);});
    ` }, bundle: true, platform: "node", format: "esm", outfile: join(root, "main.mjs"), external: ["electron"], logLevel: "silent" });
    const result = spawnSync(electron, [root, "--disable-gpu"], { windowsHide: true, encoding: "utf8", timeout: 20000,
      env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, FIXTURE_ROOT: root, FIXTURE_ADDON: addon, FIXTURE_PYTHONW: pythonw } });
    expect(result.status, String(result.error ?? result.stderr)).toBe(0);
    expect(JSON.parse(result.stdout)).toEqual({ state: "managed_drained", unmanagedSenders: "unknown", readyForCutover: false });
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 25000);
