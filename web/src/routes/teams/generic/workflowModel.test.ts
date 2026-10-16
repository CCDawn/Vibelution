import { describe, expect, it } from "vitest";
import { createWorkflow } from "./workflowTemplates";
import { mergeSavedFlows, missingInputLabels, sameFlowContent } from "./workflowModel";
import { shouldOfferGenericWorkspace, workflowTeamParams } from "./workspaceRouteModel";

describe("user-owned workflow boundaries", () => {
  it("keeps a new blank flow free of business inputs and research prerequisites", () => {
    const flow = createWorkflow("客户的流程", "blank", []);
    expect(flow.fields).toEqual([]);
    expect(flow.steps.map(step => step.kind)).toEqual(["input", "output"]);
    expect(missingInputLabels(flow, {})).toEqual([]);
    expect(flow.revision).toBe(0);
  });
  it("maps template roles onto the selected team's available members", () => {
    const flow = createWorkflow("自定义调研", "analysis", [
      { id: "unavailable", name: "Old", initial: "O", detail: "", available: false },
      { id: "real-agent", name: "One", initial: "O", detail: "", available: true },
    ]);
    expect(flow.steps.filter(step => step.kind === "agent" || step.kind === "output").every(step => step.owner === "real-agent")).toBe(true);
  });
  it("preserves a dirty draft during background refetch while refreshing clean flows", () => {
    const saved = createWorkflow("保存版", "blank", []);
    const dirty = { ...saved, name: "正在编辑" };
    const clean = { ...saved, id: "clean", name: "旧名" };
    const incoming = [{ ...saved, name: "外部修改", revision: 2 }, { ...clean, name: "新名", revision: 2 }];
    const result = mergeSavedFlows([dirty, clean], incoming, [dirty.id]);
    expect(result.map(flow => flow.name)).toEqual(["正在编辑", "新名"]);
    expect(result[0].revision).toBe(0);
    expect(sameFlowContent(saved, { ...saved, revision: 5, updatedAt: "later" })).toBe(true);
    expect(sameFlowContent(saved, dirty)).toBe(false);
  });
  it("retains unsaved new flows when the server refreshes its empty list", () => {
    const draft = createWorkflow("未保存", "blank", []);
    expect(mergeSavedFlows([draft], [], [draft.id])).toEqual([draft]);
  });
  it("leaves explicit native conversations and retained research records on their routes", () => {
    for (const query of ["teamView=tasks", "teamConversation=member", "researchView=discussion", "researchView=experiment", "workflowWorkspace=legacy", "questionId=SCI-1", "runId=run-1", "session=native"])
      expect(shouldOfferGenericWorkspace({}, new URLSearchParams(query)), query).toBe(false);
    expect(shouldOfferGenericWorkspace({ sourceCollectionStandalone: true }, new URLSearchParams())).toBe(false);
    expect(shouldOfferGenericWorkspace({}, new URLSearchParams("team=research-team&researchView=workflow&workflowId=challenge-cup-research"))).toBe(true);
  });
  it("switches team scope without carrying a previous run or research selection", () => {
    const next = workflowTeamParams(new URLSearchParams("teamId=old&workflowRunId=run-1&questionId=SCI-1&workflowId=old&teamConversation=a"), "new-team");
    expect(Object.fromEntries(next)).toEqual({ team: "new-team", teamWorkspace: "flows" });
  });
});
