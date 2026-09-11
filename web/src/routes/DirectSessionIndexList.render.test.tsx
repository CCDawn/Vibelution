/** @vitest-environment happy-dom */
import React from "react";
import { flushSync } from "react-dom";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type {
  ConversationSummary,
  SessionReferenceAttachment,
  SessionSummary,
} from "../api/types";
import type { TranslationKey } from "../i18n/dictionary";
import { DirectSessionIndexList } from "./DirectSessionIndexList";

const counters = vi.hoisted(() => ({
  viewModels: 0,
  itemProps: [] as Array<Record<string, unknown>>,
}));

vi.mock("./DirectSessionIndexItem", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./DirectSessionIndexItem")>();
  return {
    ...actual,
    buildDirectSessionIndexViewModel: (
      input: Parameters<typeof actual.buildDirectSessionIndexViewModel>[0],
    ) => {
      counters.viewModels += 1;
      return actual.buildDirectSessionIndexViewModel(input);
    },
    DirectSessionIndexItem: (
      props: Parameters<typeof actual.DirectSessionIndexItem>[0],
    ) => {
      counters.itemProps.push(props as unknown as Record<string, unknown>);
      return null;
    },
  };
});

function conversation(id: string): ConversationSummary {
  return {
    conversationId: id,
    directSessionId: id,
    title: `会话 ${id}`,
    type: "direct_agent",
    status: "idle",
    summary: "",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: `/workspace/${id}`,
    agentId: "agent-1",
    agentDisplayName: "顾明澈",
  };
}

type ListProps = Parameters<typeof DirectSessionIndexList>[0];

function listProps(overrides: Partial<ListProps> = {}): ListProps {
  return {
    activeSessionId: "s-1",
    addToReviewSucceededLabel: "",
    agentsById: new Map(),
    conversations: [conversation("s-1"), conversation("s-2")],
    deleteBusyLabel: "",
    editingSessionId: null,
    editingSessionTitle: "",
    groupPanelActive: false,
    lang: "zh",
    renameSessionId: "",
    renamePending: false,
    runtimeRunningSessionIds: [],
    sessionComposerErrors: {},
    sessionIdsNeedingApproval: [],
    sessionsById: new Map<string, SessionSummary>(),
    teams: [],
    statusLabel: () => "空闲",
    formatTime: () => "06/09 00:00",
    t: (key: TranslationKey) => key,
    avatarImageUrlFrom: () => "",
    avatarInitials: () => "S",
    buildSessionReferencePayload: (session) =>
      ({ sessionId: session.id } as unknown as SessionReferenceAttachment),
    contextMenuSessionId: "",
    isBusyPhase: () => false,
    onCancelRename: () => undefined,
    onContextMenu: () => undefined,
    onDragReference: () => undefined,
    onOpen: () => undefined,
    onPrefetch: () => undefined,
    onRenameTitleChange: () => undefined,
    onSubmitRename: () => undefined,
    ...overrides,
  };
}

describe("DirectSessionIndexList render stability", () => {
  let root: Root | null = null;
  let container: HTMLDivElement | null = null;

  beforeEach(() => {
    counters.viewModels = 0;
    counters.itemProps.length = 0;
  });

  afterEach(() => {
    if (root) {
      flushSync(() => {
        root?.unmount();
      });
    }
    container?.remove();
    root = null;
    container = null;
  });

  function renderList(props: ListProps) {
    if (!container) {
      container = document.createElement("div");
      document.body.appendChild(container);
      root = createRoot(container);
    }
    flushSync(() => {
      root?.render(<DirectSessionIndexList {...props} />);
    });
  }

  it("keeps per-session view models and item props stable across unrelated re-renders", () => {
    const props = listProps();

    renderList(props);
    expect(counters.viewModels).toBe(2);
    const firstSessionRefs = counters.itemProps.map((item) => item.session);
    const firstDragRefs = counters.itemProps.map((item) => item.onDragStart);
    const firstViewTitleRefs = counters.itemProps.map((item) => item.sessionTitle);

    renderList({ ...props, activeSessionId: "s-2" });

    expect(counters.viewModels).toBe(2);
    const secondItems = counters.itemProps.slice(2);
    expect(secondItems).toHaveLength(2);
    expect(secondItems.map((item) => item.session)).toEqual(firstSessionRefs);
    expect(secondItems.map((item) => item.onDragStart)).toEqual(firstDragRefs);
    expect(secondItems.map((item) => item.sessionTitle)).toEqual(firstViewTitleRefs);
  });

  it("rebuilds the view models as soon as a real input changes", () => {
    const props = listProps();

    renderList(props);
    expect(counters.viewModels).toBe(2);

    renderList({ ...props, sessionComposerErrors: { "s-1": "选择失败" } });
    expect(counters.viewModels).toBe(4);

    const latestItems = counters.itemProps.slice(-2);
    expect(latestItems[0].itemMessage).toBe("选择失败");
  });

  it("keeps the approval and runtime marker sets off the per-render path", () => {
    const approval = ["s-1"];
    const runtime = ["s-2"];
    const props = listProps({
      sessionIdsNeedingApproval: approval,
      runtimeRunningSessionIds: runtime,
    });

    renderList(props);
    renderList({ ...props, activeSessionId: "s-2" });

    const latestItems = counters.itemProps.slice(-2);
    expect(latestItems.map((item) => item.needsApproval)).toEqual([true, false]);
    expect(latestItems.map((item) => item.isRuntimeRunning)).toEqual([false, true]);
  });

  it("builds the drag payload at drag time, not during render", () => {
    const payloads: string[] = [];
    const props = listProps({
      buildSessionReferencePayload: (session) => {
        payloads.push(session.id);
        return { sessionId: session.id } as unknown as SessionReferenceAttachment;
      },
    });

    renderList(props);
    expect(payloads).toEqual([]);

    const dragStart = counters.itemProps[0].onDragStart as (event: unknown) => void;
    dragStart({});

    expect(payloads).toEqual(["s-1"]);
  });
});
