import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, it, vi } from "vitest";
import { AssistantHost } from "../src/assistant/assistantHost.js";

it("reports only fixed prepare diagnostics and keeps the drain boundary", async () => {
  const root = mkdtempSync(join(tmpdir(), "initial-diagnostic-"));
  const python = join(root, "pythonw.exe"); writeFileSync(python, "fixture");
  const warning = vi.spyOn(console, "warn").mockImplementation(() => undefined);
  let active = 1;
  const native = {
    spawn(input: any) {
      const runtime = input.arguments[input.arguments.indexOf("--runtime-dir") + 1];
      const id = input.arguments[input.arguments.indexOf("--instance-id") + 1];
      writeFileSync(join(runtime, "ready.json"), JSON.stringify({ protocolVersion: 1, role: "launcher_assistant", instanceId: id, pid: 1, port: 12345 }));
      return { pid: 1, job: {} };
    },
    activeCount: () => active, drainStatus: () => ({ complete: true, channels: [] }),
    terminate: () => { active = 0; return true; }, close: () => undefined,
  };
  const row = { deliveryId: "a".repeat(32), action: "initial_migration_queue" as const, projectId: "project",
    previewId: "b".repeat(64), turnId: "turn", category: "knowledge" as const,
    operationId: "initial-" + "c".repeat(40), timeoutMs: 10000 };
  const fetch = vi.fn(async (url: string | URL | Request) => {
    if (String(url).endsWith("/health")) return Response.json({ status: "ok", protocolVersion: 1, role: "launcher_assistant", initialMigrationControlVersion: 1 });
    if (String(url).endsWith("/api/assistant")) return Response.json({ assistant: { agentId: "a", directSessionId: "s", displayName: "Assistant" } });
    if (String(url).endsWith("/initial-migration/prepare")) return Response.json({ secret: "PRIVATE" });
    if (String(url).endsWith("/initial-migration/drain")) return Response.json({ schemaVersion: 1, operationId: row.operationId, state: "unknown", drained: true });
    if (String(url).endsWith("/shutdown")) { active = 0; return Response.json({ stopping: true }); }
    return Response.json({});
  });
  const host = new AssistantHost({ profileRoot: join(root, "profile"), runtimeRoot: join(root, "runtime"), sourceRoot: root,
    pythonPath: python, projects: { project: root }, initialMigrationControl: true, native: native as any, fetch: fetch as any });
  try {
    await host.start();
    expect(await host.prepareInitialMigration(row, 0)).toBe(false);
    expect(warning.mock.calls).toEqual([["ASSISTANT_INITIAL_PREPARE phase=validation code=ASSISTANT_RESPONSE_INVALID"]]);
    expect(JSON.stringify(warning.mock.calls)).not.toContain("PRIVATE");
    expect(fetch.mock.calls.some(([url]) => String(url).endsWith("/initial-migration/drain"))).toBe(true);
    await host.stop();
  } finally { warning.mockRestore(); rmSync(root, { recursive: true, force: true }); }
});
