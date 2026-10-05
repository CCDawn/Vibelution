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
    const cli = parseDesktopCliArgs(["--project", input.projectRoot, "start", "--launch-request-id", input.requestId]);
    const envelope = createSingleInstanceEnvelope({ ...cli, lifecycleCommand: cli.lifecycleCommand });
    expect(resolveSingleInstanceCliIntent(envelope).launchRequestId).toBe(input.requestId);
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
});
