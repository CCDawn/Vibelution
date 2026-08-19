/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { Team } from "../../api/types";
import { TeamShellRail } from "./TeamShellRail";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function makeTeam(teamId: string, name: string): Team {
  return {
    teamId,
    name,
    description: "",
    purpose: `${name} purpose`,
    status: "active",
    teamKind: "custom",
    teamCategory: "general",
    teamSource: "manual",
    members: [],
    memberCount: 0,
  } as Team;
}

const teams = [makeTeam("team-a", "Alpha"), makeTeam("team-b", "Beta"), makeTeam("team-c", "Gamma")];

function listbox(): HTMLElement {
  const node = document.body.querySelector<HTMLElement>('[role="listbox"]');
  if (!node) {
    throw new Error("listbox not rendered");
  }
  return node;
}

function optionId(teamId: string): string {
  const node = document.body.querySelector<HTMLElement>(`[data-testid="team-shell-item-${teamId}"]`);
  if (!node) {
    throw new Error(`option ${teamId} not rendered`);
  }
  return node.id;
}

function keydown(target: HTMLElement, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

describe("TeamShellRail listbox keyboard support", () => {
  let host: HTMLDivElement | null = null;
  let root: Root | null = null;

  afterEach(() => {
    if (root) {
      act(() => root?.unmount());
    }
    host?.remove();
    host = null;
    root = null;
  });

  function renderRail(selectedTeamId = "team-a") {
    const selected: Team[] = [];
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <TeamShellRail
          lang="en"
          teams={teams}
          selectedTeamId={selectedTeamId}
          onSelectTeam={(team) => selected.push(team)}
        />,
      );
    });
    return { selected };
  }

  it("keeps focus on the listbox and points aria-activedescendant at the selected team", () => {
    renderRail("team-b");
    const box = listbox();
    expect(box.tabIndex).toBe(0);
    expect(box.getAttribute("aria-activedescendant")).toBe(optionId("team-b"));
    for (const team of teams) {
      const option = document.body.querySelector(`[data-testid="team-shell-item-${team.teamId}"]`);
      expect(option?.getAttribute("tabindex")).toBe("-1");
      expect(option?.id).toBe(optionId(team.teamId));
    }
  });

  it("moves the active descendant with Arrow/ Home/ End keys", () => {
    renderRail("team-a");
    const box = listbox();
    keydown(box, "ArrowDown");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-b"));
    keydown(box, "ArrowDown");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-c"));
    keydown(box, "ArrowDown");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-c"));
    keydown(box, "ArrowUp");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-b"));
    keydown(box, "Home");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-a"));
    keydown(box, "End");
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-c"));
  });

  it("selects the active option with Enter and Space", () => {
    const { selected } = renderRail("team-a");
    const box = listbox();
    keydown(box, "ArrowDown");
    keydown(box, "Enter");
    expect(selected.map((team) => team.teamId)).toEqual(["team-b"]);
    keydown(box, "End");
    keydown(box, " ");
    expect(selected.map((team) => team.teamId)).toEqual(["team-b", "team-c"]);
  });

  it("keeps click selection working and adopts the clicked option as active", () => {
    const { selected } = renderRail("team-a");
    const option = document.body.querySelector<HTMLElement>('[data-testid="team-shell-item-team-c"]');
    act(() => {
      option?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(selected.map((team) => team.teamId)).toEqual(["team-c"]);
    expect(listbox().getAttribute("aria-activedescendant")).toBe(optionId("team-c"));
  });
});
