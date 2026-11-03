import { existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it, vi } from "vitest";

const fault = vi.hoisted(() => ({ kind: "", status: "" }));
vi.mock("node:fs", async original => {
  const fs = await original<typeof import("node:fs")>();
  const fail = (kind: string, path: unknown, content?: unknown) => {
    if (fault.kind !== kind || !String(path).includes("launch-requests")) return;
    if (fault.status) {
      const text = content === undefined ? fs.readFileSync(path as string, "utf8") : String(content);
      if (JSON.parse(text).status !== fault.status) return;
    }
    throw Object.assign(new Error(`injected ${kind} failure`), { code: "EACCES" });
  };
  return { ...fs,
    mkdirSync: (...args: Parameters<typeof fs.mkdirSync>) => { fail("mkdir", args[0]); return fs.mkdirSync(...args); },
    readFileSync: (...args: Parameters<typeof fs.readFileSync>) => { fail("read", args[0]); return fs.readFileSync(...args); },
    writeFileSync: (...args: Parameters<typeof fs.writeFileSync>) => { fail("write", args[0], args[1]); return fs.writeFileSync(...args); },
    renameSync: (...args: Parameters<typeof fs.renameSync>) => { fail("rename", args[0]); return fs.renameSync(...args); }
  };
});
import { beginLaunchRequestReceipt } from "../src/lifecycle/launchRequestReceipt.js";

const roots: string[] = [];
afterEach(() => { fault.kind = ""; fault.status = ""; for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });
function setup() {
  const root = mkdtempSync(join(tmpdir(), "vibelution-receipt-fault-")); roots.push(root);
  const requestId = `launch_${randomUUID().replaceAll("-", "")}`;
  const directory = join(root, ".runtime", "launcher", "launch-requests");
  return { input: { shellRoot: root, projectRoot: root, requestId, operation: "restart" },
    directory, path: join(directory, `${requestId}.json`) };
}

describe("identified launch persistence boundaries", () => {
  it.each(["mkdir", "write", "rename"])("refuses admission when received %s fails", kind => {
    const { input, directory, path } = setup(); fault.kind = kind;
    expect(() => beginLaunchRequestReceipt(input)).toThrow("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: received");
    fault.kind = "";
    expect(existsSync(path)).toBe(false);
    if (existsSync(directory)) expect(readdirSync(directory)).toEqual([]);
  });

  it.each(["write", "rename"])("does not commit handoff when its %s fails", kind => {
    const { input, path } = setup(); const receipt = beginLaunchRequestReceipt(input);
    fault.kind = kind; fault.status = "handoff";
    expect(() => receipt.handoff("start")).toThrow("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: handoff");
    expect(receipt.handedOff()).toBe(false);
    fault.kind = "";
    expect(JSON.parse(readFileSync(path, "utf8")).status).toBe("received");
    receipt.failed("handoff_failed", "The original owner remains available.");
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "failed", code: "handoff_failed" });
  });

  it.each(["write", "rename"])("publishes a negative acknowledgement after a transient received %s failure", kind => {
    const { input, path } = setup(); fault.kind = kind; fault.status = "received";
    expect(() => beginLaunchRequestReceipt(input)).toThrow("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: received");
    fault.kind = "";
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "failed", code: "launch_request_receipt_unavailable" });
    expect(beginLaunchRequestReceipt(input).duplicate).toBe(true);
  });

  it.each(["unreadable", "invalid json"])("does not treat %s feedback as an absent request", kind => {
    const { input, directory, path } = setup(); mkdirSync(directory, { recursive: true });
    writeFileSync(path, "invalid json", "utf8");
    if (kind === "unreadable") fault.kind = "read";
    expect(() => beginLaunchRequestReceipt(input)).toThrow("LAUNCH_REQUEST_RECEIPT_PERSISTENCE_FAILED: received");
    fault.kind = "";
    expect(readFileSync(path, "utf8")).toBe("invalid json");
  });

  it("preserves the unidentified legacy path when feedback storage is unavailable", () => {
    const { input } = setup(); fault.kind = "mkdir";
    expect(() => beginLaunchRequestReceipt({ ...input, requestId: undefined }).handoff("start")).not.toThrow();
  });
});
