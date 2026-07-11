import { renderToStaticMarkup } from "react-dom/server";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const queryState = vi.hoisted(() => ({
  current: {
    data: undefined as undefined | { defaultRoute?: string },
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

describe("HomeRedirect loading contract", () => {
  beforeEach(() => {
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
});
