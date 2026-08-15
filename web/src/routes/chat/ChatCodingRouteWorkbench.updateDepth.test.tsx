// @vitest-environment happy-dom
/**
 * Deterministic regression for the session-switch "Maximum update depth
 * exceeded" loop in ChatCodingRouteWorkbench.
 *
 * The active session detail query derives its placeholder from
 * `resolveSessionDetailPlaceholder` while the real detail fetch is still
 * unresolved. The previous implementation passed an inline
 * `placeholderData` callback that rebuilt that shell on every render, so a
 * no-op parent rerender handed React Query a fresh placeholder reference
 * each time and the observer snapshot churned until React bailed out with
 * "Maximum update depth exceeded" inside `forceStoreRerender`.
 *
 * `useStableSessionDetailPlaceholder` is the memoized seam: identical
 * `activeSessionId` / cached detail / summary inputs must return the same
 * placeholder reference across unrelated rerenders, and the placeholder may
 * only change when one of those inputs actually changes. This test mounts
 * only that hook.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it } from "vitest";

import type { SessionDetail, SessionSummary } from "../../api/types";
import { useStableSessionDetailPlaceholder } from "./ChatCodingRouteWorkbench";

type PlaceholderInput = {
  activeSessionId: string | null;
  cachedDetail: SessionDetail | undefined;
  summary: SessionSummary | null | undefined;
};

let snapshots: Array<{ placeholder: SessionDetail | undefined }> = [];

function Host({ input }: { input: PlaceholderInput }) {
  const placeholder = useStableSessionDetailPlaceholder(input);
  snapshots.push({ placeholder });
  return null;
}

let root: Root | null = null;
let container: HTMLElement;

function summaryFor(id: string, title: string): SessionSummary {
  return {
    id,
    title,
    agentId: "agent-1",
    agentDisplayName: "Agent",
    status: "idle",
    currentPhase: "ready",
    taskSummary: "",
    lastActive: "",
    updatedAt: "",
  };
}

function mount(input: PlaceholderInput) {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  act(() => {
    root!.render(React.createElement(Host, { input }));
  });
}

function rerender(input: PlaceholderInput) {
  act(() => {
    root!.render(React.createElement(Host, { input }));
  });
}

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
  container?.remove();
  snapshots = [];
});

describe("ChatCodingRouteWorkbench update-depth regression", () => {
  it("keeps a stable placeholder reference across no-op parent rerenders while the detail query is unresolved", () => {
    const input = {
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    };
    mount(input);
    const first = snapshots.at(-1)!;
    // Summary shell paints a provisional transcript while the fetch is pending.
    expect(first.placeholder).toBeDefined();
    expect(first.placeholder?.id).toBe("s1");
    expect(first.placeholder?.provisionalTranscript).toBe(true);

    // Same logical inputs behind a fresh props object: the no-op parent
    // rerender that previously handed React Query a brand-new shell.
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
    rerender({ ...input });
    expect(snapshots.at(-1)!.placeholder).toBe(first.placeholder);
  });

  it("recomputes the placeholder when activeSessionId changes", () => {
    mount({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    });
    const first = snapshots.at(-1)!.placeholder;

    rerender({
      activeSessionId: "s2",
      cachedDetail: undefined,
      summary: summaryFor("s2", "Session B"),
    });
    const second = snapshots.at(-1)!.placeholder;
    expect(second).not.toBe(first);
    expect(second?.id).toBe("s2");
    expect(second?.title).toBe("Session B");
  });

  it("recomputes the placeholder when the summary source changes for the same session", () => {
    mount({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A"),
    });
    const first = snapshots.at(-1)!.placeholder;

    rerender({
      activeSessionId: "s1",
      cachedDetail: undefined,
      summary: summaryFor("s1", "Session A renamed"),
    });
    const second = snapshots.at(-1)!.placeholder;
    expect(second).not.toBe(first);
    expect(second?.title).toBe("Session A renamed");
  });

  it("prefers the cached detail and keeps its reference stable", () => {
    const cached = { id: "s1", title: "Cached detail", messages: [] } as SessionDetail;
    const input = {
      activeSessionId: "s1",
      cachedDetail: cached,
      summary: summaryFor("s1", "Session A"),
    };
    mount(input);
    expect(snapshots.at(-1)!.placeholder).toBe(cached);

    // A summary-only change must not replace the cached detail placeholder.
    rerender({
      activeSessionId: "s1",
      cachedDetail: cached,
      summary: summaryFor("s1", "Session A renamed"),
    });
    expect(snapshots.at(-1)!.placeholder).toBe(cached);
  });
});
