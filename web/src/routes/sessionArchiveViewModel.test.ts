import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { beforeEach, describe, expect, it } from "vitest";

import type { ConversationSummary, SessionSummary } from "../api/types";
import {
  buildConversationIndexModel,
  conversationGroupLabel,
  isSessionArchived,
  isVisibleDirectSession,
  isVisibleConversation,
  resetConversationIndexModelStabilizationForTests,
} from "./conversationIndexModel";

const workbenchSource = readFileSync(resolve(import.meta.dirname, "chat/ChatCodingRouteWorkbench.tsx"), "utf8");
const railSource = readFileSync(resolve(import.meta.dirname, "chat/ChatConversationIndexRail.tsx"), "utf8");
const menuSource = readFileSync(resolve(import.meta.dirname, "SessionContextMenu.tsx"), "utf8");

function session(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return {
    id: "session-1",
    title: "用户会话",
    status: "idle",
    taskSummary: "摘要",
    lastActive: "2026-06-09T00:00:00.000Z",
    updatedAt: "2026-06-09T00:00:00.000Z",
    currentPhase: "idle",
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
    ...overrides,
  };
}

function conversation(overrides: Partial<ConversationSummary> = {}): ConversationSummary {
  return {
    conversationId: "session-1",
    directSessionId: "session-1",
    type: "direct_agent",
    title: "用户会话",
    status: "idle",
    summary: "摘要",
    updatedAt: "2026-06-09T00:00:00.000Z",
    workspacePath: "C:/workspace",
    conversationIndexKind: "user_chat",
    conversationIndexErrors: [],
    ...overrides,
  };
}

function archivedSession(overrides: Partial<SessionSummary> = {}): SessionSummary {
  return session({
    id: "session-archived",
    title: "已归档会话",
    hiddenFromIndex: true,
    readOnly: true,
    archiveState: { status: "archived", source: "session_archive", archivedAt: "2026-06-01T00:00:00.000Z" },
    ...overrides,
  });
}

function buildModel(overrides: Record<string, unknown> = {}, extraSessions: SessionSummary[] = []) {
  const archived = extraSessions.length ? extraSessions : [];
  const sessions = [...archived];
  return buildConversationIndexModel({
    agents: [],
    conversations: [],
    includeArchivedSessions: true,
    lang: "zh",
    linkedTeamRoomIds: new Set<string>(),
    rawSessions: sessions,
    rightIndexSessions: sessions,
    sessionFilter: "",
    sessionsById: new Map(sessions.map((item) => [item.id, item])),
    teams: [],
    ...overrides,
  });
}

describe("session archive visibility", () => {
  beforeEach(() => {
    resetConversationIndexModelStabilizationForTests();
  });

  it("flags archived sessions from the archiveState metadata", () => {
    expect(isSessionArchived(archivedSession())).toBe(true);
    expect(isSessionArchived(session())).toBe(false);
  });

  it("keeps archived sessions out of the default list but shows them in the archived view", () => {
    const archived = archivedSession();
    expect(isVisibleDirectSession(archived)).toBe(false);
    expect(isVisibleDirectSession(archived, { includeArchivedSessions: true })).toBe(true);
  });

  it("keeps hidden non-archived sessions excluded even in the archived view", () => {
    const hidden = session({ hiddenFromIndex: true });
    expect(isVisibleDirectSession(hidden)).toBe(false);
    expect(isVisibleDirectSession(hidden, { includeArchivedSessions: true })).toBe(false);
  });

  it("gates archived conversation rows through the same archived-view option", () => {
    const archived = archivedSession();
    const row = conversation({
      conversationId: archived.id,
      directSessionId: archived.id,
      conversationIndexKind: "hidden",
      conversationIndexVisibility: "hidden",
    });
    const sessionsById = new Map([[archived.id, archived]]);
    expect(isVisibleConversation(row, sessionsById)).toBe(false);
    expect(isVisibleConversation(row, sessionsById, { includeArchivedSessions: true })).toBe(true);
  });

  it("renders a dedicated archived group only when the archived view is on", () => {
    const archived = archivedSession();
    const withArchived = buildModel({}, [archived]);
    const archivedGroup = withArchived.groupedConversations.find((group) => group.groupKey === "archived");
    expect(archivedGroup).toBeDefined();
    expect(archivedGroup?.items.map((item) => item.directSessionId || item.conversationId)).toContain(archived.id);
    expect(conversationGroupLabel("archived", "zh")).toBe("已归档");
    expect(conversationGroupLabel("archived", "en")).toBe("Archived");

    const defaultModel = buildConversationIndexModel({
      agents: [],
      conversations: [],
      lang: "zh",
      linkedTeamRoomIds: new Set<string>(),
      rawSessions: [archived],
      rightIndexSessions: [archived],
      sessionFilter: "",
      sessionsById: new Map([[archived.id, archived]]),
      teams: [],
    });
    expect(defaultModel.groupedConversations.find((group) => group.groupKey === "archived")).toBeUndefined();
  });

  it("drops archived rows from the model when the archived view is off", () => {
    const archived = archivedSession();
    const defaultModel = buildModel({ includeArchivedSessions: false }, [archived]);
    const allGroupItems = defaultModel.groupedConversations.flatMap((group) =>
      group.items.map((item) => item.directSessionId || item.conversationId),
    );
    expect(allGroupItems).not.toContain(archived.id);
  });
});

describe("session archive UI wiring", () => {
  it("offers archive/unarchive from the existing session context menu", () => {
    expect(menuSource).toContain('id: "archive"');
    expect(menuSource).toContain("ArchiveRestore");
    expect(menuSource).toContain('t("archiveSession")');
    expect(menuSource).toContain('t("unarchiveSession")');
    expect(menuSource).toContain("onArchive");
    expect(menuSource).toContain("archivePending");
  });

  it("toggles the archived view from the conversation index rail header", () => {
    expect(railSource).toContain('data-vui="session-archive-toggle"');
    expect(railSource).toContain("aria-pressed={showArchivedSessions}");
    expect(railSource).toContain("onToggleShowArchivedSessions");
    expect(railSource).toContain("显示已归档会话");
  });

  it("routes archive actions and archived data through the workbench", () => {
    expect(workbenchSource).toContain("sessionArchiveMutation");
    expect(workbenchSource).toContain("archiveChatSession");
    expect(workbenchSource).toContain("unarchiveChatSession");
    expect(workbenchSource).toContain("handleArchiveSession");
    expect(workbenchSource).toContain("includeArchivedSessions: showArchivedSessions");
    expect(workbenchSource).toContain("rawSessionsWithArchived");
    expect(workbenchSource).toContain("onArchive={handleArchiveSession}");
    expect(workbenchSource).toContain('queryKey: queryKeys.sessionArchive()');
  });
});
