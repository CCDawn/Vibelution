import { spawnSync } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { buildSync } from "esbuild";
import { expect, it } from "vitest";

const addon = process.env.VIBELUTION_MUTEX_TEST_ADDON;
const pythonw = process.env.VIBELUTION_TEST_PYTHONW;
const electron = resolve("node_modules/electron/dist/electron.exe");
it.skipIf(!addon || !pythonw || !existsSync(electron))("uses the real Electron main and Python private receipt RPC across host restart", () => {
  const root = realpathSync.native(mkdtempSync(join(tmpdir(), "legacy-private-rpc-")));
  try {
    mkdirSync(join(root, "scripts"));
    writeFileSync(join(root, "scripts", "assistant_host.py"), `
import argparse, json, os, socket, sys
from pathlib import Path
sys.path.insert(0, os.environ['FIXTURE_SOURCE'])
import uvicorn
import core.assistant_runtime.host as host
import core.assistant_runtime.reminders as reminders
import core.assistant_runtime.legacy_reminder_receipts as legacy
original_receipts = legacy.LegacyReminderReceipts
class FixtureReceipts(original_receipts):
    def reserve(self, request):
        try: return super().reserve(request)
        except Exception:
            import traceback
            traceback.print_exc()
            raise
legacy.LegacyReminderReceipts = FixtureReceipts
class FakeReminders:
    def __init__(self, *args): pass
    def close(self): pass
reminders.LauncherReminders = FakeReminders
class FakeNative:
    def __init__(self, root):
        self.root = Path(root)
        self.assistant = {'agentId':'fixture', 'directSessionId':'session', 'displayName':'Fixture'}
    def bootstrap(self): return {'assistant': self.assistant}
    def shutdown(self): pass
host.NativeFacade = FakeNative
parser = argparse.ArgumentParser()
parser.add_argument('--profile-root'); parser.add_argument('--runtime-dir'); parser.add_argument('--instance-id'); parser.add_argument('--projects-file')
args = parser.parse_args()
sock = socket.socket(); sock.bind(('127.0.0.1', 0)); sock.listen(16)
server = None
def ready():
    Path(args.runtime_dir, 'ready.json').write_text(json.dumps({'protocolVersion':1,'role':'launcher_assistant','instanceId':args.instance_id,'pid':os.getpid(),'port':sock.getsockname()[1]}))
def shutdown(): server.should_exit = True
app = host.create_app(native=FakeNative(args.profile_root), token=os.environ['VIBELUTION_ASSISTANT_TOKEN'], on_ready=ready, on_shutdown=shutdown)
server = uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False))
server.run(sockets=[sock])
`, "utf8");
    const script = join(root, "electron-main.mjs");
    writeFileSync(join(root, "package.json"), JSON.stringify({ name: "legacy-rpc-fixture", version: "1.0.0", type: "module", main: "electron-main.mjs" }));
    const source = resolve("src/assistant/assistantHost.ts");
    buildSync({ stdin: { resolveDir: process.cwd(), sourcefile: "fixture.ts", contents: `
      import { app } from 'electron'; import { createRequire } from 'node:module'; import { join } from 'node:path';
      import { AssistantHost } from ${JSON.stringify(source)};
      app.setPath('userData',join(process.env.FIXTURE_ROOT,'electron-data')); app.disableHardwareAcceleration();
      app.whenReady().then(async () => {
        const root=process.env.FIXTURE_ROOT, native=createRequire(import.meta.url)(process.env.FIXTURE_ADDON);
        const options={profileRoot:join(root,'profile'),runtimeRoot:join(root,'runtime'),sourceRoot:root,pythonPath:process.env.FIXTURE_PYTHONW,
          projects:{},native,env:{FIXTURE_SOURCE:process.env.FIXTURE_SOURCE}};
        const eventId='affair-reminder:fixture:'+new Date().toISOString().slice(0,10).replaceAll('-',''), sourceKey='a'.repeat(64);
        const first=new AssistantHost(options); await first.start();
        const reservation=await first.reserveLegacyReminder({sourceKey,eventId});
        const before=await first.inventoryLegacyReminders();
        await first.settleLegacyReminder({sourceKey,eventId,attemptToken:reservation.attemptToken,channel:'system_notification'});
        await first.stop();
        const second=new AssistantHost(options); await second.start();
        const after=await second.inventoryLegacyReminders();
        const duplicate=await second.reserveLegacyReminder({sourceKey,eventId});
        await second.stop();
        process.stdout.write(JSON.stringify({before,after,duplicate})); app.exit(0);
      }).catch(error=>{process.stderr.write(String(error && error.stack || error));app.exit(1);});
    ` }, bundle: true, platform: "node", format: "esm", outfile: script, external: ["electron"], logLevel: "silent" });
    const result = spawnSync(electron, [root, "--disable-gpu"], { windowsHide: true, encoding: "utf8", timeout: 30000,
      env: { ...process.env, ELECTRON_RUN_AS_NODE: undefined, FIXTURE_ROOT: root, FIXTURE_ADDON: addon,
        FIXTURE_PYTHONW: pythonw, FIXTURE_SOURCE: resolve("../..") } });
    if (result.status !== 0) {
      const logs = join(root, "runtime");
      const detail = existsSync(logs) ? readdirSync(logs).map(name => {
        const path = join(logs, name, "stderr.log"); return existsSync(path) ? readFileSync(path, "utf8").slice(-8000) : "";
      }).join("\n") : "";
      throw new Error(`fixture failed: ${result.error ?? result.stderr} ${detail}`);
    }
    const parsed = JSON.parse(result.stdout);
    expect(parsed.before.records).toHaveLength(1);
    expect(parsed.before.records[0]).toMatchObject({ state: "pending", inflight: true });
    expect(parsed.after.records[0]).toMatchObject({ state: "submitted", channel: "system_notification", inflight: false });
    expect(parsed.duplicate.state).toBe("submitted");
  } finally { rmSync(root, { recursive: true, force: true }); }
}, 70000);
