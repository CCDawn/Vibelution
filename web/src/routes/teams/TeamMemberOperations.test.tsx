/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentConfigWorkspaceAgent, Team } from "../../api/types";
import { TeamMemberOperations, type TeamMemberOperationsProps } from "./TeamMemberOperations";
import type { UseTeamSettingsActionsOptions } from "./useTeamSettingsActions";

const mock = vi.hoisted(() => ({
  submit: vi.fn(), reset: vi.fn(), pending: false, errorMessage: "",
  options: {} as UseTeamSettingsActionsOptions,
}));

vi.mock("./useTeamSettingsActions", () => ({
  useTeamSettingsActions: (options: UseTeamSettingsActionsOptions) => {
    mock.options = options;
    return { submit: mock.submit, reset: mock.reset, pending: mock.pending, errorMessage: mock.errorMessage };
  },
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const agents = ["a", "b", "c", "occupied"].map((agentId) => ({
  agentId, displayName: `Agent ${agentId}`, status: "active", llmBindings: {},
})) as AgentConfigWorkspaceAgent[];
const agentsById: ReadonlyMap<string, AgentConfigWorkspaceAgent> = new Map(agents.map((agent) => [agent.agentId, agent]));

function makeTeam(patch: Partial<Team> = {}): Team {
  return {
    teamId: "team", name: "Team", description: "Original", purpose: "Purpose", status: "active",
    teamKind: "custom", systemManaged: false,
    members: [
      { memberId: "first", agentId: "a", agentName: "Alpha", role: "lead", purpose: "Coordinate", responsibilities: ["Plan"], agentStatus: "active" },
      { memberId: "second", agentId: "b", agentName: "Beta", role: "reviewer", purpose: "Review", responsibilities: ["Verify"], agentStatus: "active" },
    ],
    ...patch,
  } as Team;
}

describe("TeamMemberOperations", () => {
  let root: Root;
  let host: HTMLDivElement;
  let props: TeamMemberOperationsProps;

  function render(patch: Partial<TeamMemberOperationsProps> = {}) {
    props = { ...props, ...patch };
    act(() => root.render(<TeamMemberOperations {...props} />));
  }
  function button(text: string) {
    const result = Array.from(host.querySelectorAll("button")).find((node) => node.textContent?.includes(text));
    expect(result).toBeTruthy();
    return result!;
  }
  function click(text: string) {
    act(() => button(text).click());
  }
  function select(value: string) {
    const node = host.querySelector("select")!;
    act(() => {
      node.value = value;
      node.dispatchEvent(new Event("change", { bubbles: true }));
    });
  }

  beforeEach(() => {
    mock.submit.mockReset(); mock.reset.mockReset(); mock.pending = false; mock.errorMessage = "";
    host = document.createElement("div"); document.body.append(host); root = createRoot(host);
    props = { lang: "zh", team: makeTeam(), memberId: "first", agents, teams: [], agentsById,
      onSyncRoom: vi.fn(), syncPending: false };
  });
  afterEach(() => {
    act(() => root.unmount()); host.remove();
  });

  it("edits inline through the settings hook and preserves the latest sibling roster", () => {
    render();
    expect(host.textContent).toContain("人物操作");
    expect(host.textContent).toContain("Agent a");
    expect(host.querySelector("select")).toBeNull();
    click("配置成员");
    expect(button("配置成员").getAttribute("aria-expanded")).toBe("true");
    expect(document.querySelector('[role="dialog"]')).toBeNull();
    expect(button("应用配置").disabled).toBe(true);
    select("c");
    const team = makeTeam();
    team.members[1] = { ...team.members[1], role: "updated reviewer", responsibilities: ["New requirement"] };
    render({ team });
    click("应用配置");
    expect(mock.submit).toHaveBeenCalledExactlyOnceWith("team", { members: [
      { memberId: "first", agentId: "c", role: "lead", purpose: "Coordinate", responsibilities: ["Plan"] },
      { memberId: "second", agentId: "b", role: "updated reviewer", purpose: "Review", responsibilities: ["New requirement"] },
    ] });
    act(() => mock.options.onSaved?.(team));
    expect(host.querySelector("select")).toBeNull();
  });

  it("opens on recovery revisions and allows stale repair using the same available agent", () => {
    const team = makeTeam(); team.members[0] = { ...team.members[0], agentStatus: "stale" };
    render({ team, configureRevision: 1 });
    expect(host.textContent).toContain("当前成员配置不可用");
    expect(button("应用配置").disabled).toBe(false);
    click("应用配置");
    expect(mock.submit.mock.calls[0][1].members[0]).toMatchObject({ memberId: "first", agentId: "a" });
    click("配置成员");
    expect(host.querySelector("select")).toBeNull();
    render({ configureRevision: 2 });
    expect(host.querySelector("select")).not.toBeNull();
  });

  it.each([
    { status: "archived" },
    { systemManaged: true },
    { systemManaged: undefined, teamKind: "research" },
  ] as Partial<Team>[])("keeps readonly teams locked: %j", (patch) => {
    render({ team: makeTeam(patch), configureRevision: 1 });
    expect(button("配置成员").disabled).toBe(true);
    expect(host.querySelector("select")?.disabled).toBe(true);
    expect(button("应用配置").disabled).toBe(true);
    click("应用配置");
    expect(mock.submit).not.toHaveBeenCalled();
  });

  it("rejects occupied and missing agent choices while keeping recovery available", () => {
    const other = makeTeam({ teamId: "other", members: [{ ...makeTeam().members[0], agentId: "occupied" }] });
    render({ teams: [other], configureRevision: 1 });
    expect(host.querySelector<HTMLOptionElement>('option[value="occupied"]')?.disabled).toBe(true);
    select("occupied");
    expect(button("应用配置").disabled).toBe(true);
    const team = makeTeam(); team.members[0] = { ...team.members[0], agentId: "missing", agentStatus: "stale" };
    render({ team });
    expect(button("应用配置").disabled).toBe(true);
    select("c"); click("应用配置");
    expect(mock.submit.mock.calls[0][1].members[0].agentId).toBe("c");
  });

  it("preserves pending and error states for save and shell-owned synchronization", () => {
    render({ configureRevision: 1 }); select("c");
    mock.pending = true; mock.errorMessage = "保存失败";
    render({ syncError: "同步失败" });
    expect(button("配置成员").disabled).toBe(true);
    expect(host.querySelector("select")?.disabled).toBe(true);
    expect(button("应用配置").getAttribute("aria-busy")).toBe("true");
    click("同步会话"); expect(props.onSyncRoom).not.toHaveBeenCalled();
    expect(Array.from(host.querySelectorAll('[role="alert"]')).map((node) => node.textContent)).toEqual(["保存失败", "同步失败"]);
    mock.pending = false;
    render({ syncPending: true });
    expect(button("同步会话").getAttribute("aria-busy")).toBe("true");
    expect(button("应用配置").disabled).toBe(true);
    render({ syncPending: false, syncDisabledReason: "团队运行中" });
    expect(button("同步会话").disabled).toBe(true);
    expect(host.textContent).toContain("团队运行中");
    render({ syncDisabledReason: "" }); click("同步会话");
    expect(props.onSyncRoom).toHaveBeenCalledOnce();
    expect(host.querySelector("select")?.value).toBe("c");
  });

  it("keeps the submitted member identity when selection changes during a save", () => {
    const onSaved = vi.fn();
    render({configureRevision:1,onSaved});select("c");click("应用配置");
    mock.pending = true;render({memberId:"second",configureRevision:0});
    act(() => mock.options.onSaved?.(makeTeam()));
    expect(onSaved).toHaveBeenCalledWith(expect.objectContaining({teamId:"team"}),"first");
  });

  it("handles a missing member without exposing a roster mutation", () => {
    render({ memberId: "deleted", configureRevision: 1 });
    expect(host.textContent).toContain("未选择成员");
    expect(host.querySelector("button")).toBeNull();
    expect(mock.submit).not.toHaveBeenCalled();
  });
});
