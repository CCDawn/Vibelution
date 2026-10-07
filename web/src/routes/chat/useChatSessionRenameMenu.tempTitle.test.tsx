// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../../api/queryKeys";
import type { SessionDetail, SessionSummary } from "../../api/types";
import type { TranslationKey } from "../../i18n/dictionary";
import { buildSessionCreateShell } from "./chatSessionCreateRecovery";
import { useChatSessionRenameMenu } from "./useChatSessionRenameMenu";

const tempSession = {
  id: "temp-session-rename",
  title: "新会话",
  agentId: "agent-a",
} as SessionSummary;

let root: Root | null = null;
let queryClient: QueryClient;
let menu: ReturnType<typeof useChatSessionRenameMenu> | null = null;
const setEditingSessionId = vi.fn();
const setEditingSessionTitle = vi.fn();
const setSessionComposerErrors = vi.fn();
const renameSession = vi.fn();

function Host({ title }: { title: string }) {
  menu = useChatSessionRenameMenu({
    t: (key: TranslationKey) => key,
    navigate: vi.fn() as never,
    editingSessionTitle: title,
    setEditingSessionId,
    setEditingSessionTitle,
    setSessionContextMenu: vi.fn(),
    setSessionComposerErrors,
    renameSession,
    suppressRenameBlurUntilRef: { current: 0 },
  });
  return null;
}

beforeEach(() => {
  setEditingSessionId.mockReset();
  setEditingSessionTitle.mockReset();
  setSessionComposerErrors.mockReset();
  renameSession.mockReset();
  menu = null;
  queryClient = new QueryClient();
  queryClient.setQueryData(
    queryKeys.session(tempSession.id),
    buildSessionCreateShell({
      tempSessionId: tempSession.id,
      agentId: "agent-a",
      idempotencyKey: "session-create:test",
      createdAt: "2026-01-01T00:00:00.000Z",
    }, "新会话", "测试助手"),
  );
  const container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(() => {
  act(() => {
    root?.unmount();
  });
  root = null;
});

describe("temporary session tab rename", () => {
  it("keeps an explicit title on the temp shell and closes the editor", () => {
    act(() => {
      root!.render(
        React.createElement(QueryClientProvider, { client: queryClient }, React.createElement(Host, { title: "茅台临时改名" })),
      );
    });
    act(() => {
      menu!.submitRenameSession(tempSession, { reason: "explicit" });
    });
    expect(queryClient.getQueryData<SessionDetail>(queryKeys.session(tempSession.id))?.title).toBe("茅台临时改名");
    expect(setEditingSessionId).toHaveBeenCalledWith(null);
    expect(renameSession).not.toHaveBeenCalled();
  });
});
