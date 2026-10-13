import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ConfigSummary } from "../api/types";

const queryState = vi.hoisted(() => ({
  current: {
    data: undefined as undefined | Partial<ConfigSummary>,
    error: null as unknown,
    isError: false,
    isFetching: true,
    isPending: true,
    refetch: vi.fn(),
  },
}));

vi.mock("@tanstack/react-query", () => ({ useQuery: () => queryState.current }));
vi.mock("react-router-dom", () => ({
  Navigate: ({ to }: { to: string }) => <span data-navigate-to={to} />,
}));

import { HomeRedirect } from "./HomeRedirect";
import { readCurrentChatSelectionPreference } from "./chat/useChatSelectionPersistence";

vi.mock("./chat/useChatSelectionPersistence", () => ({ readCurrentChatSelectionPreference: vi.fn() }));

describe("HomeRedirect loading contract", () => {
  beforeEach(() => {
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue(null);
    queryState.current = {
      data: undefined,
      error: null,
      isError: false,
      isFetching: true,
      isPending: true,
      refetch: vi.fn(),
    };
  });

  it("renders a visible workbench shell while config is pending", () => {
    const markup = renderToStaticMarkup(<HomeRedirect />);
    expect(markup).toContain('data-vui-app="workbench"');
    expect(markup).toContain('aria-busy="true"');
    expect(markup).toContain("正在确定默认工作台");
  });

  it("renders a local error surface instead of guessing a route", () => {
    queryState.current = {
      ...queryState.current,
      isError: true,
      isFetching: false,
      isPending: false,
      error: new Error("config unavailable"),
    };
    const markup = renderToStaticMarkup(<HomeRedirect />);
    expect(markup).toContain('data-tone="error"');
    expect(markup).toContain("config unavailable");
    expect(markup).not.toContain("data-navigate-to");
  });

  it("restores the last Agent through the validated bare chat entry before the default homepage", () => {
    queryState.current = { ...queryState.current, data: { defaultRoute: "/self-evolution" }, isPending: false, isFetching: false };
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ agentId: "last-agent", sessionId: "old-session" });
    expect(renderToStaticMarkup(<HomeRedirect />)).toContain('data-navigate-to="/chat"');
  });

  it("keeps the configured homepage for a fresh profile or disabled chat", () => {
    queryState.current = { ...queryState.current, data: { defaultRoute: "/self-evolution" }, isPending: false, isFetching: false };
    expect(renderToStaticMarkup(<HomeRedirect />)).toContain('data-navigate-to="/self-evolution"');
    vi.mocked(readCurrentChatSelectionPreference).mockReturnValue({ agentId: "last-agent" });
    queryState.current.data = { defaultRoute: "/self-evolution", domainAvailability: { chat: false, evolution: true } };
    expect(renderToStaticMarkup(<HomeRedirect />)).toContain('data-navigate-to="/self-evolution"');
  });
});
