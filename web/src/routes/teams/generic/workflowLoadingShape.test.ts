/** @vitest-environment happy-dom */
import { afterEach, expect, it, vi } from "vitest";
import { createWorkflow } from "./workflowTemplates";
import { readWorkflowLoadingShape, rememberWorkflowLoadingShape } from "./workflowLoadingShape";

const key = "vibelution.team-flow-loading-shapes.v1";
afterEach(() => { vi.restoreAllMocks(); localStorage.clear(); });
const flow = () => ({ ...createWorkflow("private name", "blank", []), revision: 1,
  description: "private description", fields: [{ id: "private-field", label: "private input", kind: "select" as const, required: true, options: ["secret option"] }] });

it("retains only structural hints and isolates teams", () => {
  const saved = flow(); saved.steps[0].instruction = "private prompt"; saved.steps[0].owner = "private-agent";
  rememberWorkflowLoadingShape("team-a", [saved]);
  const hint = readWorkflowLoadingShape("team-a")!;
  expect(hint[0].steps.map(step => step.kind)).toEqual(saved.steps.map(step => step.kind));
  expect(hint[0].fields.map(field => field.kind)).toEqual(["select"]);
  expect(readWorkflowLoadingShape("team-b")).toBeUndefined();
  for (const privateText of ["private", "secret option", saved.id]) expect(localStorage.getItem(key)).not.toContain(privateText);
});

it("lets successful empty responses replace stale editor hints", () => {
  rememberWorkflowLoadingShape("team-a", [flow()]);
  rememberWorkflowLoadingShape("team-a", []);
  expect(readWorkflowLoadingShape("team-a")).toEqual([]);
});

it.each(["{bad", JSON.stringify({ "team-a": { at: Date.now(), flows: [{steps: ["invalid"], fields: []}] } }),
  JSON.stringify({ "team-a": { at: 1, flows: [] } })])("rejects corrupt or stale hints and heals after a successful read", raw => {
  localStorage.setItem(key, raw);
  expect(readWorkflowLoadingShape("team-a")).toBeUndefined();
  rememberWorkflowLoadingShape("team-a", [flow()]);
  expect(readWorkflowLoadingShape("team-a")).toHaveLength(1);
});

it("never blocks workflow reads when storage is denied", () => {
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => { throw new Error("denied"); });
  expect(() => rememberWorkflowLoadingShape("team-a", [flow()])).not.toThrow();
  expect(readWorkflowLoadingShape("team-a")).toBeUndefined();
});
