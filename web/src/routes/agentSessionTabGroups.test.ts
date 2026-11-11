/** @vitest-environment happy-dom */
import { beforeEach, describe, expect, it } from "vitest";

import type { SessionSummary } from "../api/types";
import {
  UNGROUPED_SECTION_ID,
  assignSessionToTabGroup,
  mergeSessionsIntoTabGroup,
  sessionTabGroupColorFor,
  setAgentSessionTabGroupColor,
  createAgentSessionTabGroup,
  defaultAgentSessionTabGroupName,
  deleteAgentSessionTabGroup,
  emptyAgentSessionTabGroupState,
  pruneSessionTabGroupMembership,
  readAgentSessionTabGroupState,
  renameAgentSessionTabGroup,
  resolveSessionTabGroupSections,
  sessionTabGroupIdFor,
  setAgentSessionTabGroupCollapsed,
  writeAgentSessionTabGroupState,
} from "./agentSessionTabGroups";

function session(id: string): SessionSummary {
  return {
    id,
    title: id,
    status: "idle",
    taskSummary: "",
    lastActive: "2026-01-01T00:00:00Z",
    updatedAt: "2026-01-01T00:00:00Z",
    currentPhase: "",
  } as SessionSummary;
}

const sessions = [session("s1"), session("s2"), session("s3")];

beforeEach(() => {
  window.localStorage.clear();
});

describe("agentSessionTabGroups", () => {
  it("creates groups with distinct default names", () => {
    const first = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "分组 1", {
      id: "g1",
    });
    const second = createAgentSessionTabGroup(first.state, "", { id: "g2" });
    expect(first.state.groups.map((group) => group.id)).toEqual(["g1"]);
    expect(second.state.groups.map((group) => group.name)).toEqual(["分组 1", "分组 2"]);
    expect(defaultAgentSessionTabGroupName(second.state)).toBe("分组 3");
  });

  it("assigns one session to at most one group (folder semantics)", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = createAgentSessionTabGroup(state, "B", { id: "gb" }).state;
    state = assignSessionToTabGroup(state, "s1", "ga");
    state = assignSessionToTabGroup(state, "s1", "gb");
    expect(state.membership.s1).toBe("gb");
    expect(sessionTabGroupIdFor(state, "s1")).toBe("gb");
  });

  it("moves a session back to the ungrouped fallback", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = assignSessionToTabGroup(state, "s1", "ga");
    state = assignSessionToTabGroup(state, "s1", null);
    expect(state.membership).toEqual({});
    expect(sessionTabGroupIdFor(state, "s1")).toBe(UNGROUPED_SECTION_ID);
  });

  it("ignores unknown group ids so a stale drop target cannot invent members", () => {
    const state = emptyAgentSessionTabGroupState();
    expect(assignSessionToTabGroup(state, "s1", "missing")).toBe(state);
  });

  it("renames, collapses and deletes groups, releasing members on delete", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = assignSessionToTabGroup(state, "s1", "ga");
    state = renameAgentSessionTabGroup(state, "ga", "  Review  ");
    expect(state.groups[0].name).toBe("Review");
    expect(renameAgentSessionTabGroup(state, "ga", "   ")).toBe(state);
    state = setAgentSessionTabGroupCollapsed(state, "ga", true);
    expect(state.groups[0].collapsed).toBe(true);
    state = deleteAgentSessionTabGroup(state, "ga");
    expect(state.groups).toEqual([]);
    expect(state.membership).toEqual({});
  });

  it("renders only non-empty groups with the ungrouped section last", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = createAgentSessionTabGroup(state, "B", { id: "gb" }).state;
    state = assignSessionToTabGroup(state, "s2", "ga");
    const sections = resolveSessionTabGroupSections(sessions, state);
    expect(sections.map((section) => section.groupId)).toEqual(["ga", UNGROUPED_SECTION_ID]);
    expect(sections[0].sessions.map((item) => item.id)).toEqual(["s2"]);
    expect(sections[1].sessions.map((item) => item.id)).toEqual(["s1", "s3"]);
    expect(sections[1].ungrouped).toBe(true);
  });

  it("drops the ungrouped section when every session is grouped", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    for (const item of sessions) {
      state = assignSessionToTabGroup(state, item.id, "ga");
    }
    const sections = resolveSessionTabGroupSections(sessions, state);
    expect(sections.map((section) => section.groupId)).toEqual(["ga"]);
  });

  it("prunes membership for sessions that no longer exist", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = assignSessionToTabGroup(state, "s1", "ga");
    state = assignSessionToTabGroup(state, "gone", "ga");
    const pruned = pruneSessionTabGroupMembership(state, ["s1", "s2"]);
    expect(pruned.membership).toEqual({ s1: "ga" });
    expect(pruneSessionTabGroupMembership(pruned, ["s1", "s2"])).toBe(pruned);
  });

  it("persists per agent and tolerates a dangling group reference", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = assignSessionToTabGroup(state, "s1", "ga");
    writeAgentSessionTabGroupState("agent-a", state);
    expect(readAgentSessionTabGroupState("agent-a").membership).toEqual({ s1: "ga" });
    expect(readAgentSessionTabGroupState("agent-b")).toEqual(emptyAgentSessionTabGroupState());

    window.localStorage.setItem(
      "vibelution.agentSessionTabGroups.v1",
      JSON.stringify({ "agent-c": { groups: [], membership: { s9: "gone" } } }),
    );
    expect(readAgentSessionTabGroupState("agent-c")).toEqual({
      groups: [],
      membership: {},
    });
  });

  it("clears storage when the last group is deleted", () => {
    const { state } = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    });
    writeAgentSessionTabGroupState("agent-a", state);
    writeAgentSessionTabGroupState("agent-a", deleteAgentSessionTabGroup(state, "ga"));
    expect(window.localStorage.getItem("vibelution.agentSessionTabGroups.v1")).toBeNull();
  });

  it("survives corrupt storage payloads", () => {
    window.localStorage.setItem("vibelution.agentSessionTabGroups.v1", "{not json");
    expect(readAgentSessionTabGroupState("agent-a")).toEqual(emptyAgentSessionTabGroupState());
  });

  it("sets and clears a group colour, degrading unknown colours from storage", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "A", {
      id: "ga",
    }).state;
    state = setAgentSessionTabGroupColor(state, "ga", "blue");
    expect(state.groups[0].color).toBe("blue");
    expect(sessionTabGroupColorFor(state, "ga")).toBe("blue");
    state = setAgentSessionTabGroupColor(state, "ga", null);
    expect(state.groups[0].color).toBeUndefined();
    expect(sessionTabGroupColorFor(state, "ga")).toBeNull();

    window.localStorage.setItem(
      "vibelution.agentSessionTabGroups.v1",
      JSON.stringify({
        "agent-x": {
          groups: [{ id: "g", name: "A", collapsed: false, color: "chartreuse" }],
          membership: {},
        },
      }),
    );
    expect(readAgentSessionTabGroupState("agent-x").groups[0].color).toBeUndefined();
  });

  it("merges two sessions into a brand-new group, moving them out of the old one", () => {
    let state = createAgentSessionTabGroup(emptyAgentSessionTabGroupState(), "旧组", {
      id: "old",
    }).state;
    state = assignSessionToTabGroup(state, "s1", "old");
    const merged = mergeSessionsIntoTabGroup(state, ["s1", "s2"], "分组 2", { id: "new" });
    expect(merged.groupId).toBe("new");
    expect(merged.state.membership).toEqual({ s1: "new", s2: "new" });
    expect(merged.state.groups.map((group) => group.id)).toEqual(["old", "new"]);
  });

  it("does not create a group when fewer than two sessions are dropped", () => {
    const state = emptyAgentSessionTabGroupState();
    expect(mergeSessionsIntoTabGroup(state, ["s1", "s1"], "分组 1", { id: "n" }).state).toBe(state);
  });
});
