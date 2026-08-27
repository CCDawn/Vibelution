// @vitest-environment happy-dom
/**
 * Chat route single-authority contract (Task 2).
 *
 * Real committed-location verification through createMemoryRouter +
 * RouterProvider: the URL is the only active Chat selection, the sole writer
 * is useChatRouteSelection, and window focus/visibility/pageshow events can
 * never navigate.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import {
  createMemoryRouter,
  RouterProvider,
  useNavigationType,
  type Router,
} from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  activeGroupRoomIdFromRouteSelection,
  activeSessionIdFromRouteSelection,
  chatRouteSelectionsEqual,
  chatRouteSelectionKey,
  parseChatRouteSelection,
  PROJECT_AGENT_BUS_ROOM_ID,
  serializeChatRouteSelection,
} from "./chatSelectionProjection";
import { useChatRouteSelection } from "./useChatRouteSelection";

let hostResults: ReturnType<typeof useChatRouteSelection>[] = [];
let observedNavigationTypes: string[] = [];

function Host() {
  hostResults.push(useChatRouteSelection());
  observedNavigationTypes.push(useNavigationType());
  return <div data-testid="host" />;
}

let router: Router;
let root: Root | null = null;
let container: HTMLElement;

function mount(initialEntries: string[]) {
  router = createMemoryRouter(
    [{ path: "/chat", element: React.createElement(Host) }],
    { initialEntries },
  );
  observedNavigationTypes = [];
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(React.createElement(RouterProvider, { router }));
  });
}

function committedSearch(): string {
  return router.state.location.search;
}

function flush() {
  act(() => undefined);
}

function latest() {
  return hostResults[hostResults.length - 1];
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  hostResults = [];
});

describe("chat route selection model", () => {
  it("parses session, room, project bus, bare and invalid routes", () => {
    expect(parseChatRouteSelection("?session=session-a")).toEqual({
      kind: "session",
      sessionId: "session-a",
    });
    expect(parseChatRouteSelection("?room=room-team")).toEqual({ kind: "room", roomId: "room-team" });
    expect(parseChatRouteSelection(`?room=${PROJECT_AGENT_BUS_ROOM_ID}`)).toEqual({
      kind: "project_bus",
    });
    expect(parseChatRouteSelection("")).toEqual({ kind: "bare" });
    expect(parseChatRouteSelection("?focusTask=t1")).toEqual({ kind: "bare" });
    expect(parseChatRouteSelection("?session=a&room=b")).toEqual({
      kind: "invalid",
      reason: "conflicting_session_and_room",
    });
  });

  it("serializes route targets while preserving unrelated query params", () => {
    expect(serializeChatRouteSelection("?focusTask=t1&focusTurn=2", { kind: "session", sessionId: "s" }))
      .toBe("?focusTask=t1&focusTurn=2&session=s");
    expect(serializeChatRouteSelection("?session=old&filter=recent", { kind: "room", roomId: "r" }))
      .toBe("?filter=recent&room=r");
    expect(serializeChatRouteSelection("?room=old", { kind: "project_bus" }))
      .toBe(`?room=${PROJECT_AGENT_BUS_ROOM_ID}`);
    expect(serializeChatRouteSelection("?session=old", { kind: "bare" })).toBe("");
  });

  it("derives active ids only from route kinds", () => {
    expect(activeSessionIdFromRouteSelection({ kind: "session", sessionId: "s" })).toBe("s");
    expect(activeSessionIdFromRouteSelection({ kind: "room", roomId: "r" })).toBe("");
    expect(activeGroupRoomIdFromRouteSelection({ kind: "room", roomId: "r" })).toBe("r");
    expect(activeGroupRoomIdFromRouteSelection({ kind: "project_bus" }))
      .toBe(PROJECT_AGENT_BUS_ROOM_ID);
  });

  it("compares route selections by kind and id for compare-and-swap", () => {
    expect(chatRouteSelectionsEqual(
      { kind: "session", sessionId: "a" },
      { kind: "session", sessionId: "a" },
    )).toBe(true);
    expect(chatRouteSelectionsEqual(
      { kind: "session", sessionId: "a" },
      { kind: "session", sessionId: "b" },
    )).toBe(false);
    expect(chatRouteSelectionsEqual(
      { kind: "room", roomId: "r" },
      { kind: "project_bus" },
    )).toBe(false);
    expect(chatRouteSelectionKey({ kind: "project_bus" }))
      .toBe(chatRouteSelectionKey({ kind: "room", roomId: PROJECT_AGENT_BUS_ROOM_ID }));
  });
});

describe("useChatRouteSelection committed-location contract", () => {
  it("derives the current selection only from the committed URL", () => {
    mount(["/chat?session=session-a"]);
    expect(latest().selection).toEqual({ kind: "session", sessionId: "session-a" });
    expect(latest().matchesSelection({ kind: "session", sessionId: "session-a" })).toBe(true);

    act(() => {
      router.navigate("/chat?room=room-team");
    });
    expect(latest().selection).toEqual({ kind: "room", roomId: "room-team" });
    expect(latest().matchesSelection({ kind: "session", sessionId: "session-a" })).toBe(false);
  });

  it("openSession commits a replace navigation to the session route", () => {
    mount(["/chat?session=session-a"]);
    act(() => {
      latest().openSession("session-b");
    });
    expect(committedSearch()).toContain("session=session-b");
    expect(committedSearch()).not.toContain("session=session-a");
    // replace does not push a new history entry (tab-click semantics).
    expect(observedNavigationTypes).toContain("REPLACE");
    expect(observedNavigationTypes).not.toContain("PUSH");
  });

  it("openSession preserves unrelated deep-link params", () => {
    mount(["/chat?session=session-a&focusTask=t1&focusTurn=2"]);
    act(() => {
      latest().openSession("session-b");
    });
    expect(committedSearch()).toContain("focusTask=t1");
    expect(committedSearch()).toContain("focusTurn=2");
    expect(committedSearch()).toContain("session=session-b");
  });

  it("opens a companion through the sole Chat route writer and clears that context on ordinary navigation", () => {
    mount(["/chat"]);
    act(() => {
      latest().openCompanionSession("session-nora", "agent/nora", {
        returnLabel: "人物大厅",
      });
    });
    expect(router.state.location.pathname).toBe("/chat");
    expect(committedSearch()).toContain("session=session-nora");
    expect(committedSearch()).toContain("companion=agent%2Fnora");
    expect(committedSearch()).toContain("returnTo=%2Fcompanions");
    expect(committedSearch()).toContain("returnLabel=%E4%BA%BA%E7%89%A9%E5%A4%A7%E5%8E%85");

    act(() => {
      latest().openSession("session-ordinary");
    });
    expect(committedSearch()).toBe("?session=session-ordinary");
  });

  it("openRoom pushes and openProjectBus commits the explicit project bus route", () => {
    mount(["/chat?session=session-a"]);
    act(() => {
      latest().openRoom("room-team");
    });
    expect(committedSearch()).toBe(`?room=room-team`);
    act(() => {
      latest().openProjectBus();
    });
    expect(committedSearch()).toBe(`?room=${PROJECT_AGENT_BUS_ROOM_ID}`);
    expect(observedNavigationTypes).toContain("PUSH");
  });

  it("canonicalizes a bare route exactly once per location key", () => {
    mount(["/chat"]);
    expect(latest().selection.kind).toBe("bare");
    act(() => {
      latest().canonicalizeBareRoute({ kind: "session", sessionId: "session-a" });
    });
    expect(committedSearch()).toContain("session=session-a");
    act(() => {
      latest().canonicalizeBareRoute({ kind: "session", sessionId: "session-b" });
    });
    expect(committedSearch()).toContain("session=session-a");
    expect(committedSearch()).not.toContain("session=session-b");
  });

  it("never canonicalizes an explicit route", () => {
    mount(["/chat?room=room-team"]);
    act(() => {
      latest().canonicalizeBareRoute({ kind: "session", sessionId: "session-a" });
    });
    expect(committedSearch()).toBe("?room=room-team");
  });

  it("replaceIfStillViewing applies a transition only while the user still views the expected target", () => {
    mount(["/chat?session=temp-session-1"]);
    act(() => {
      const applied = latest().replaceIfStillViewing(
        { kind: "session", sessionId: "temp-session-1" },
        { kind: "session", sessionId: "real-session-9" },
      );
      expect(applied).toBe(true);
    });
    expect(committedSearch()).toContain("session=real-session-9");

    act(() => {
      latest().openSession("session-elsewhere");
    });
    act(() => {
      const applied = latest().replaceIfStillViewing(
        { kind: "session", sessionId: "temp-session-1" },
        { kind: "session", sessionId: "real-session-9" },
      );
      expect(applied).toBe(false);
    });
    expect(committedSearch()).toContain("session=session-elsewhere");
    expect(committedSearch()).not.toContain("session=real-session-9");
  });

  it("keeps the committed URL unchanged on focus, visibility, pageshow and passive clicks", () => {
    mount(["/chat?session=session-a"]);
    act(() => {
      window.dispatchEvent(new Event("focus"));
      document.dispatchEvent(new Event("visibilitychange"));
      window.dispatchEvent(new PageTransitionEvent("pageshow"));
      window.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });
    flush();
    expect(committedSearch()).toBe("?session=session-a");
    expect(latest().selection).toEqual({ kind: "session", sessionId: "session-a" });
  });
});
