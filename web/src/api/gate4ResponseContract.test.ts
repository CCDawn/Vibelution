import { describe, expect, it } from "vitest";

// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { readFileSync } from "node:fs";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { join } from "node:path";
// @ts-expect-error Vitest runs this contract in Node; the web project intentionally omits global Node types.
import { fileURLToPath } from "node:url";

import { researchWorkflowStreamUrl } from "./research-workflow/events";

const apiRoot = fileURLToPath(new URL("./", import.meta.url));
const repoRoot = join(apiRoot, "../../..");

function pythonModelFields(source: string, className: string): string[] {
  const marker = `class ${className}`;
  const start = source.indexOf(marker);
  if (start < 0) {
    throw new Error(`missing Python model ${className}`);
  }
  const rest = source.slice(start);
  const nextClass = rest.indexOf("\nclass ", marker.length);
  const body = nextClass >= 0 ? rest.slice(0, nextClass) : rest;
  return [...body.matchAll(/^\s{4}([A-Za-z_][A-Za-z0-9_]*):/gm)]
    .map((match) => match[1])
    .filter((name) => name !== "model_config");
}

function typescriptTypeBody(source: string, typeName: string): string {
  const marker = `export type ${typeName} = {`;
  const start = source.indexOf(marker);
  if (start < 0) {
    throw new Error(`missing TypeScript type ${typeName}`);
  }
  return source.slice(start, start + 2500);
}

describe("Gate 4 frontend consumption of typed runtime contracts", () => {
  it("keeps LauncherStatus fields aligned with the published Python envelope", () => {
    const python = readFileSync(join(repoRoot, "core/launcher/api_contract.py"), "utf-8");
    const typescript = readFileSync(join(apiRoot, "types/runtime.ts"), "utf-8");
    const statusBody = typescriptTypeBody(typescript, "LauncherStatus");
    const fields = pythonModelFields(python, "LauncherStatusResponse");
    expect(fields.length).toBeGreaterThan(8);
    const missing = fields.filter((field) => !statusBody.includes(field));
    expect(missing).toEqual([]);
    expect(statusBody).toContain("controlPlaneEvidence");
    expect(statusBody).toContain("guardianAdapter");
    expect(statusBody).toContain("overallState");
  });

  it("keeps research snapshot/event page extras and the SSE stream URL", () => {
    const snapshot = readFileSync(join(apiRoot, "types/research-workflow/core.ts"), "utf-8");
    const events = readFileSync(join(apiRoot, "research-workflow/events.ts"), "utf-8");
    const models = readFileSync(
      join(repoRoot, "core/web/routes/team_workflows/research_runtime_models.py"),
      "utf-8",
    );
    expect(typescriptTypeBody(snapshot, "ResearchWorkflowSnapshot")).toContain("generatedAt");
    expect(typescriptTypeBody(snapshot, "ResearchWorkflowNodeDetail")).toContain("commandOffers");
    expect(events).toContain("export type EventPage");
    expect(models).toContain('extra="allow"');
    expect(models).toContain("class ResearchWorkflowRunSnapshotResponse");
    expect(researchWorkflowStreamUrl({ runId: "run-1", teamId: "research-team" })).toBe(
      "/api/research/workflow-runs/run-1/stream?teamId=research-team",
    );
    expect(researchWorkflowStreamUrl({ runId: "run-1", teamId: "research-team", afterSequence: 4 })).toContain(
      "afterSequence=4",
    );
  });
});
