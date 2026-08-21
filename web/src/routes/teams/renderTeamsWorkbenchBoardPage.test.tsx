/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("../../components/vui", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../../components/vui")>();
  return {
    ...actual,
    VBoardWorkbenchPage: (props: {
      layoutId?: string;
      rail?: React.ReactNode;
      railClassName?: string;
      workspaceClassName?: string;
    }) => (
      <div
        data-testid="mock-board-workbench"
        data-layout-id={props.layoutId ?? ""}
        data-rail-present={props.rail ? "true" : "false"}
        data-rail-class={props.railClassName ?? ""}
        data-workspace-class={props.workspaceClassName ?? ""}
      />
    ),
  };
});

import {
  renderTeamsWorkbenchBoardPage,
  TeamsWorkbenchInspectorOverlay,
  type TeamsWorkbenchBoardPageProps,
} from "./renderTeamsWorkbenchBoardPage";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const styles: Record<string, string> = {
  boardInspectorOverlayBackdrop: "backdrop",
  boardInspectorOverlayPanel: "panel",
  boardInspectorOverlayHeader: "header",
  boardInspectorOverlayBody: "body",
};

const baseBoardProps: TeamsWorkbenchBoardPageProps = {
  lang: "zh",
  styles: { route: "route" },
  teamsRailResize: {
    sidebar: { id: "rail", defaultWidth: 280, minWidth: 240, maxWidth: 360 },
    aside: { id: "inspector", defaultWidth: 360, minWidth: 300, maxWidth: 520 },
  },
  selectedTeamContextTitle: "挑战杯科研团队",
  teamShellRail: <aside data-testid="team-shell-rail" />,
  teamShellToolbar: <div data-testid="team-shell-toolbar" />,
  boardPrimaryMode: "overview",
  workflowPending: false,
  workflowReady: true,
  challengeCupResearchTeamSelected: true,
  overviewSlot: null,
  stageSlot: null,
  launcherSlot: null,
  showBoardInspectorAside: false,
  inspectorBody: null,
};

function keydown(target: Element, key: string) {
  act(() => {
    target.dispatchEvent(new KeyboardEvent("keydown", { key, bubbles: true, cancelable: true }));
  });
}

describe("TeamsWorkbenchInspectorOverlay", () => {
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

  function renderOverlay(onDismiss: () => void) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(
        <TeamsWorkbenchInspectorOverlay
          styles={styles}
          label="Detail panel"
          dismissLabel="Close detail panel"
          onDismiss={onDismiss}
        >
          <button type="button" data-testid="inner-control">
            Inner control
          </button>
        </TeamsWorkbenchInspectorOverlay>,
      );
    });
    const backdrop = document.body.querySelector<HTMLElement>(
      '[data-vui-region="teams-inspector-overlay-backdrop"]',
    );
    if (!backdrop) {
      throw new Error("backdrop not rendered");
    }
    return { backdrop };
  }

  it("exposes the backdrop as a focusable dismiss control", () => {
    const { backdrop } = renderOverlay(() => undefined);
    expect(backdrop.getAttribute("role")).toBe("button");
    expect(backdrop.getAttribute("tabindex")).toBe("0");
    expect(backdrop.getAttribute("aria-label")).toBe("Close detail panel");
  });

  it("closes on Escape from the backdrop and from inside the panel", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    keydown(backdrop, "Escape");
    expect(dismissals).toBe(1);
    const inner = document.body.querySelector<HTMLElement>('[data-testid="inner-control"]');
    keydown(inner as HTMLElement, "Escape");
    expect(dismissals).toBe(2);
  });

  it("closes on Enter/Space only when the backdrop itself is the key target", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    keydown(backdrop, "Enter");
    keydown(backdrop, " ");
    expect(dismissals).toBe(2);
    const inner = document.body.querySelector<HTMLElement>('[data-testid="inner-control"]');
    keydown(inner as HTMLElement, "Enter");
    keydown(inner as HTMLElement, " ");
    expect(dismissals).toBe(2);
  });

  it("keeps click-to-dismiss on the backdrop but not on the panel", () => {
    let dismissals = 0;
    const { backdrop } = renderOverlay(() => {
      dismissals += 1;
    });
    act(() => {
      backdrop.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dismissals).toBe(1);
    const panel = document.body.querySelector<HTMLElement>('[data-vui-region="teams-inspector-overlay"]');
    act(() => {
      panel?.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    expect(dismissals).toBe(1);
    expect(panel?.getAttribute("role")).toBe("region");
    expect(panel?.getAttribute("aria-label")).toBe("Detail panel");
  });
});

describe("renderTeamsWorkbenchBoardPage outer shell chrome", () => {
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

  function renderBoard(overrides: Partial<TeamsWorkbenchBoardPageProps> = {}) {
    host = document.createElement("div");
    document.body.appendChild(host);
    root = createRoot(host);
    act(() => {
      root?.render(renderTeamsWorkbenchBoardPage({ ...baseBoardProps, ...overrides }));
    });
    const shell = document.body.querySelector<HTMLElement>('[data-testid="mock-board-workbench"]');
    if (!shell) {
      throw new Error("board workbench mock not rendered");
    }
    return shell;
  }

  it("removes the generic rail and persisted outer layout for the Challenge Cup workflow", () => {
    const shell = renderBoard({ suppressOuterShellChrome: true });

    expect(shell.getAttribute("data-layout-id")).toBe("");
    expect(shell.getAttribute("data-rail-present")).toBe("false");
    expect(shell.getAttribute("data-rail-class")).toBe("!hidden");
    expect(shell.getAttribute("data-workspace-class")).toBe("!grid-cols-[minmax(0,1fr)]");
  });

  it("keeps the generic rail and persisted layout for ordinary Teams surfaces", () => {
    const shell = renderBoard({
      challengeCupResearchTeamSelected: false,
      suppressOuterShellChrome: false,
    });

    expect(shell.getAttribute("data-layout-id")).toBeTruthy();
    expect(shell.getAttribute("data-rail-present")).toBe("true");
    expect(shell.getAttribute("data-rail-class")).toBe("");
    expect(shell.getAttribute("data-workspace-class")).toBe("");
  });
});
