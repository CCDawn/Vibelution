import { mkdirSync, mkdtempSync, readFileSync, readdirSync, rmSync, utimesSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { randomUUID } from "node:crypto";
import { afterEach, describe, expect, it } from "vitest";
import { beginLaunchRequestReceipt, normalizeLaunchRequestId } from "../src/lifecycle/launchRequestReceipt.js";
import { createSingleInstanceEnvelope, resolveSingleInstanceCliIntent } from "../src/appLock.js";
import { parseDesktopCliArgs } from "../src/cli/desktopCli.js";

const roots: string[] = [];
afterEach(() => { for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true }); });

describe("launch preparation receipts", () => {
  function setup() {
    const root = mkdtempSync(join(tmpdir(), "vibelution-launch-receipt-"));
    roots.push(root);
    const requestId = `launch_${randomUUID().replaceAll("-", "")}`;
    const input = { shellRoot: root, projectRoot: join(root, "task"), operation: "start", requestId };
    const path = join(root, ".runtime", "launcher", "launch-requests", `${requestId}.json`);
    return { input, path, root };
  }

  it("round-trips the request through CLI and envelope without granting provenance", () => {
    const { input } = setup();
    const cli = parseDesktopCliArgs(["--project", input.projectRoot, "start", "--launch-request-id", input.requestId,
      "--launch-request-operation", "restart", "--launch-request-handoff-pid", "123"]);
    const envelope = createSingleInstanceEnvelope({ ...cli, lifecycleCommand: cli.lifecycleCommand });
    expect(resolveSingleInstanceCliIntent(envelope).launchRequestId).toBe(input.requestId);
    expect(resolveSingleInstanceCliIntent(envelope)).toMatchObject({ launchRequestOperation: "restart", launchRequestHandoffPid: 123 });
    expect(envelope.lifecycle.provenance).toBe("operator");
    expect(parseDesktopCliArgs(["--launch-request-id", "start"]).lifecycleCommand).toBe("");
    expect(normalizeLaunchRequestId("../receipt")).toBe("");
  });

  it("publishes receipt before preparation, reports failure, and suppresses duplicate delivery", () => {
    const { input, path } = setup();
    const receipt = beginLaunchRequestReceipt(input);
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "received", requestId: input.requestId, projectRoot: input.projectRoot });
    receipt.failed("frontend_preparation_failed", "Frontend preparation failed.");
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "failed", code: "frontend_preparation_failed" });
    expect(beginLaunchRequestReceipt(input).duplicate).toBe(true);
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "failed" });
    expect(readdirSync(join(input.shellRoot, ".runtime", "launcher", "launch-requests"))).toEqual([`${input.requestId}.json`]);
  });

  it("routing completion records dispatch, not ready or successful startup", () => {
    const { input, path } = setup();
    beginLaunchRequestReceipt(input).dispatched();
    const receipt = JSON.parse(readFileSync(path, "utf8"));
    expect(receipt.status).toBe("dispatched");
    expect(receipt.accepted).toBeUndefined();
    expect(receipt.generation).toBeUndefined();
  });

  it("invalid request IDs cannot create a receipt path", () => {
    const { input, root } = setup();
    beginLaunchRequestReceipt({ ...input, requestId: "../../escape" }).failed("error", "failure");
    expect(readdirSync(root)).toEqual([]);
  });

  it("reaps abandoned atomic-write files while preserving unrelated files", () => {
    const { input, path } = setup();
    const directory = join(input.shellRoot, ".runtime", "launcher", "launch-requests");
    mkdirSync(directory, { recursive: true });
    const abandoned = `${path}.123.tmp`;
    writeFileSync(abandoned, "partial");
    utimesSync(abandoned, new Date(0), new Date(0));
    writeFileSync(join(directory, "unrelated.tmp"), "keep");
    beginLaunchRequestReceipt(input);
    expect(readdirSync(directory).sort()).toEqual([`${input.requestId}.json`, "unrelated.tmp"].sort());
  });

  it.each(["received", "dispatched", "completed", "failed"])("does not replay persisted %s from another owner", status => {
    const { input, path } = setup();
    mkdirSync(join(input.shellRoot, ".runtime", "launcher", "launch-requests"), { recursive: true });
    const previous = { ...input, shellPid: 123, status, updatedAt: new Date().toISOString() };
    writeFileSync(path, JSON.stringify(previous));
    expect(beginLaunchRequestReceipt(input).duplicate).toBe(true);
    expect(JSON.parse(readFileSync(path, "utf8"))).toEqual(previous);
  });

  it("only resumes an explicit fresh handoff and publishes the new READY owner", () => {
    const { input, path } = setup();
    mkdirSync(join(input.shellRoot, ".runtime", "launcher", "launch-requests"), { recursive: true });
    writeFileSync(path, JSON.stringify({ schemaVersion: 1, requestId: input.requestId, projectRoot: input.projectRoot,
      operation: input.operation, shellPid: 123, status: "handoff", updatedAt: new Date().toISOString() }));
    const resumed = beginLaunchRequestReceipt({ ...input, handoffFromPid: 123 });
    expect(resumed.duplicate).toBe(false);
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "received", shellPid: process.pid, handoffFromPid: 123 });
    resumed.dispatched("cmd_replacement"); resumed.completed("cmd_replacement", true);
    expect(JSON.parse(readFileSync(path, "utf8"))).toMatchObject({ status: "completed", operation: "start",
      completion: { ownerPid: process.pid, commandId: "cmd_replacement", ready: true } });
    resumed.failed("late_failure", "Late callbacks cannot replace completion.");
    expect(JSON.parse(readFileSync(path, "utf8")).status).toBe("completed");
  });

  it.each(["missing time", "wrong owner", "wrong operation"])("refuses an unproven handoff: %s", failure => {
    const { input, path } = setup();
    mkdirSync(join(input.shellRoot, ".runtime", "launcher", "launch-requests"), { recursive: true });
    writeFileSync(path, JSON.stringify({ schemaVersion: 1, requestId: input.requestId, projectRoot: input.projectRoot,
      operation: failure === "wrong operation" ? "restart" : input.operation,
      shellPid: failure === "wrong owner" ? 456 : 123, status: "handoff",
      ...(failure === "missing time" ? {} : { updatedAt: new Date().toISOString() }) }));
    expect(beginLaunchRequestReceipt({ ...input, handoffFromPid: 123 }).duplicate).toBe(true);
  });
});
