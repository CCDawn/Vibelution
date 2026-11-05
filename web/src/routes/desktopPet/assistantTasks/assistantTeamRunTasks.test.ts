import { describe, expect, it } from "vitest";
import type { LauncherAssistantTeamRun, LauncherAssistantTeamRunsPage } from "../../../api/launcherAssistant";
import { assistantTeamRunPageNeedsRefresh, projectAssistantTeamRunTasks, retainAssistantTeamRunDisplay } from "./assistantTeamRunTasks";

function run(overrides: Partial<LauncherAssistantTeamRun> = {}): LauncherAssistantTeamRun {
  return { projectId: "project-1", requestId: "request-1", originAction: "team_run", teamId: "team-1", flowId: "flow-1",
    runId: "run-1", status: "running", revision: "r1", title: "团队周报", readState: "ready",
    observedAt: "2026-11-02T01:00:00Z", businessAcceptance: "not_evaluated", ...overrides };
}

function page(teamRuns: LauncherAssistantTeamRun[]): LauncherAssistantTeamRunsPage {
  return { schemaVersion: 1, assistant: { agentId: "assistant-1", directSessionId: "session-1" }, teamRuns,
    offset: 0, total: teamRuns.length, nextCursor: null, state: "ready",
    coverage: { kind: "local_associations", historyComplete: false, legacyUnrecoverable: 0, invalidRecords: 0 } };
}

function unknown(overrides: Partial<LauncherAssistantTeamRun> = {}): LauncherAssistantTeamRun {
  return run({ teamId: null, flowId: null, runId: null, status: null, revision: null, title: "", observedAt: null,
    readState: "unknown", ...overrides });
}

describe("assistant team run projection", () => {
  it.each([
    { name: "ready empty source", state: "ready", rows: [], legacy: 0, invalid: 0, needsRefresh: false },
    { name: "ready current observation", state: "ready", rows: [run()], legacy: 0, invalid: 0, needsRefresh: false },
    { name: "unexplained partial empty source", state: "partial", rows: [], legacy: 0, invalid: 0, needsRefresh: true },
    { name: "unexplained partial current observation", state: "partial", rows: [run()], legacy: 0, invalid: 0, needsRefresh: true },
    { name: "only a legacy gap with no team rows", state: "partial", rows: [], legacy: 2, invalid: 0, needsRefresh: false },
    { name: "only a legacy gap with ready rows", state: "partial", rows: [run()], legacy: 2, invalid: 0, needsRefresh: false },
    { name: "unknown row despite ready page state", state: "ready", rows: [unknown()], legacy: 2, invalid: 0, needsRefresh: true },
    { name: "unknown row alongside a legacy gap", state: "partial", rows: [unknown()], legacy: 2, invalid: 0, needsRefresh: true },
    { name: "mixed ready and unknown rows", state: "partial", rows: [run(), unknown({ requestId: "request-2" })], legacy: 2, invalid: 0, needsRefresh: true },
    { name: "invalid record despite ready page state", state: "ready", rows: [], legacy: 0, invalid: 1, needsRefresh: true },
    { name: "invalid record alongside a legacy gap", state: "partial", rows: [run()], legacy: 2, invalid: 1, needsRefresh: true },
  ] as const)("classifies $name without changing native coverage", ({ state, rows, legacy, invalid, needsRefresh }) => {
    const observed = { ...page([...rows]), state,
      coverage: { kind: "local_associations" as const, historyComplete: false as const, legacyUnrecoverable: legacy, invalidRecords: invalid } };
    const before = structuredClone(observed);
    expect(assistantTeamRunPageNeedsRefresh(observed)).toBe(needsRefresh);
    expect(observed).toEqual(before);
  });

  it.each([
    ["running", "running", true], ["waiting", "waiting_input", true],
    ["completed", "awaiting_verification", false], ["failed", "failed", false],
    ["stopped", "stopped", false], ["unfamiliar", "unknown", false], ["queued", "unknown", false],
  ] as const)("projects native %s without inventing business acceptance", (status, state, shouldPoll) => {
    expect(projectAssistantTeamRunTasks([run({ status })]).tasks[0]).toMatchObject({
      kind: "team_run", state, shouldPoll, businessAcceptance: "not_evaluated",
    });
  });

  it("trusts status only for ready observations with all owning references bound", () => {
    for (const row of [run({ teamId: null }), run({ flowId: null }), run({ runId: null }), run({ readState: "unknown" })]) {
      expect(projectAssistantTeamRunTasks([row]).tasks[0]).toMatchObject({ state: "unknown", shouldPoll: false });
    }
    expect(projectAssistantTeamRunTasks([run({ status: "completed" })], { sourceAvailable: false }).tasks[0])
      .toMatchObject({ state: "unknown", sourceAvailable: false, shouldPoll: false, receiptBound: false,
        teamId: null, flowId: null, runId: null, nativeStatus: null, revision: null, observedAt: null,
        lastKnown: { teamId: "team-1", flowId: "flow-1", runId: "run-1", revision: "r1" } });
  });

  it("uses all project/team/flow/run references and tuple encoding for stable deduplication", () => {
    const row = run();
    const tasks = projectAssistantTeamRunTasks([row, { ...row, observedAt: "later read" },
      run({ projectId: "project-2" }), run({ teamId: "team-2" }), run({ flowId: "flow-2" }), run({ runId: "run-2" }),
      run({ teamId: "a:b", flowId: "c" }), run({ teamId: "a", flowId: "b:c" })]).tasks;
    expect(tasks).toHaveLength(7);
    expect(new Set(tasks.map(task => task.id)).size).toBe(7);
    expect(tasks[0].conflictingObservations).toBe(false);
  });

  it("keeps unbound requests separate by project, action and request identity", () => {
    const pending = { teamId: null, flowId: null, runId: null };
    const tasks = projectAssistantTeamRunTasks([run(pending), run({ ...pending, requestId: "request-2" }),
      run({ ...pending, originAction: "flow_start" }), run({ ...pending, projectId: "project-2" })]).tasks;
    expect(tasks).toHaveLength(4);
    expect(tasks.every(task => task.state === "unknown")).toBe(true);
  });

  it("preserves conflicts as unknown instead of selecting a possibly stale successful observation", () => {
    const tasks = projectAssistantTeamRunTasks([run(), run({ status: "completed", revision: "r2" }), run()]).tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0]).toMatchObject({ state: "unknown", conflictingObservations: true, receiptBound: false, shouldPoll: false });
  });

  it("deduplicates consistent aliases while retaining their original assistant request references", () => {
    const tasks = projectAssistantTeamRunTasks([run({ title: "" }),
      run({ requestId: "request-2", originAction: "flow_start", title: "流程名称" })]).tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0]).toMatchObject({ state: "running", conflictingObservations: false, title: "流程名称",
      sourceRefs: [{ requestId: "request-1", originAction: "team_run" }, { requestId: "request-2", originAction: "flow_start" }] });
  });

  it("bounds untrusted title text, rejects missing request identity and leaves inputs untouched", () => {
    const row = run({ title: `标题\u202e${"长".repeat(150)}` });
    const before = structuredClone(row);
    const result = projectAssistantTeamRunTasks([row, run({ requestId: "" })]);
    expect(result.invalidRecords).toBe(1);
    expect(Array.from(result.tasks[0].title)).toHaveLength(100);
    expect(result.tasks[0].title).not.toContain("\u202e");
    expect(row).toEqual(before);
  });

  it("retains only display metadata through successful unknown reads without restoring native authority", () => {
    const ready = page([run()]);
    const current = page([unknown()]);
    const before = structuredClone(current);
    const observed = retainAssistantTeamRunDisplay(current, [ready]);
    expect(current).toEqual(before);
    expect(observed.teamRuns[0]).toMatchObject({ readState: "unknown", status: null, teamId: null, flowId: null, runId: null,
      revision: null, observedAt: null, lastKnown: { title: "团队周报", teamId: "team-1", flowId: "flow-1", runId: "run-1", revision: "r1" } });
    const task = projectAssistantTeamRunTasks(observed.teamRuns).tasks[0];
    expect(task.id).toBe(projectAssistantTeamRunTasks(ready.teamRuns).tasks[0].id);
    expect(task).toMatchObject({ state: "unknown", title: "团队周报", nativeStatus: null, receiptBound: false, shouldPoll: false,
      teamId: null, flowId: null, runId: null, observedAt: null, revision: null });
    const repeated = retainAssistantTeamRunDisplay(current, [observed]);
    expect(repeated.teamRuns[0].lastKnown).toEqual(observed.teamRuns[0].lastKnown);
    const recovered = retainAssistantTeamRunDisplay(page([run({ title: "新标题", revision: "r2" })]), [repeated]);
    expect(recovered.teamRuns[0].lastKnown).toBeUndefined();
    expect(projectAssistantTeamRunTasks(recovered.teamRuns).tasks[0]).toMatchObject({ title: "新标题", revision: "r2", state: "running" });
  });

  it("requires the exact assistant, project, action and request for display retention", () => {
    const ready = page([run()]);
    for (const current of [
      { ...page([unknown()]), assistant: { agentId: "assistant-2", directSessionId: "session-1" } },
      { ...page([unknown()]), assistant: { agentId: "assistant-1", directSessionId: "session-2" } },
      page([unknown({ projectId: "project-2" })]), page([unknown({ originAction: "flow_start" })]),
      page([unknown({ requestId: "request-2" })]),
    ]) expect(retainAssistantTeamRunDisplay(current, [ready]).teamRuns[0].lastKnown).toBeUndefined();
  });

  it("keeps unknown aliases in one native group without retaining requests deleted from the snapshot", () => {
    const alias = { requestId: "request-2", originAction: "flow_start" as const };
    const ready = page([run(), run(alias)]);
    const observed = retainAssistantTeamRunDisplay(page([unknown(), unknown(alias)]), [ready]);
    const tasks = projectAssistantTeamRunTasks(observed.teamRuns).tasks;
    expect(tasks).toHaveLength(1);
    expect(tasks[0]).toMatchObject({ state: "unknown", receiptBound: false, shouldPoll: false });
    expect(tasks[0].sourceRefs).toHaveLength(2);
    const removed = retainAssistantTeamRunDisplay(page([]), [observed]);
    expect(removed.teamRuns).toEqual([]);
    expect(retainAssistantTeamRunDisplay(page([unknown()]), [removed]).teamRuns[0].lastKnown).toBeUndefined();
    const onlyAlias = retainAssistantTeamRunDisplay(page([unknown(alias)]), [observed]);
    expect(projectAssistantTeamRunTasks(onlyAlias.teamRuns).tasks[0].sourceRefs).toEqual([alias]);
  });
});
