/** @vitest-environment happy-dom */
import React, { act } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderToStaticMarkup } from "react-dom/server";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { queryKeys } from "../api/queryKeys";
import { MemoryUserContentPanel } from "./MemoryUserContentPanel";

const contentApiMocks = vi.hoisted(() => ({
  fetchUserMarkdownSpacePage: vi.fn(),
  importUserMarkdownSpace: vi.fn(),
  listUserMarkdownSpacePages: vi.fn(),
  listUserMarkdownSpaces: vi.fn(),
  previewUserMarkdownSpaceImport: vi.fn(),
  searchUserMarkdownSpaces: vi.fn(),
}));

vi.mock("../api/userContent", () => contentApiMocks);

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement | null = null;
let root: Root | null = null;

const space = {
  spaceId: "space-1",
  spaceName: "Research notes",
  canonicalPagesRoot: "C:/notes/research",
  indexRoot: "C:/notes/research/.index",
  pageCount: 1,
  updatedAt: "2026-10-03T00:00:00Z",
  userId: "default",
  counts: { markdownFileCount: 1, pageCount: 1, linkCount: 0, taskCount: 0, tagCount: 0 },
};

const page = {
  pageId: "page-1",
  relativePath: "overview.md",
  title: "Overview",
  tags: [],
  wikilinks: [],
  taskCounts: { open: 0, done: 0, total: 0 },
  contentHash: "hash-1",
  byteSize: 9,
  updatedAt: "2026-10-03T00:00:00Z",
};

function renderPanel(queryClient: QueryClient) {
  host = document.createElement("div");
  document.body.appendChild(host);
  root = createRoot(host);
  act(() => {
    root?.render(
      <QueryClientProvider client={queryClient}>
        <MemoryUserContentPanel />
      </QueryClientProvider>,
    );
  });
  return host;
}

async function flushEffects() {
  await act(async () => {
    await new Promise<void>((resolve) => window.setTimeout(resolve, 0));
  });
}

afterEach(async () => {
  if (root) {
    await act(async () => root?.unmount());
  }
  host?.remove();
  root = null;
  host = null;
  vi.clearAllMocks();
});

describe("MemoryUserContentPanel page detail state", () => {
  it("shows the empty state while the page query is disabled", () => {
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    const markup = renderToStaticMarkup(
      <QueryClientProvider client={queryClient}>
        <MemoryUserContentPanel />
      </QueryClientProvider>,
    );

    expect(markup).toContain("未选择页面");
    expect(markup).not.toContain("正在读取页面");
    expect(markup).not.toContain('aria-busy="true"');
  });

  it("shows loading while the selected page request is actually fetching", async () => {
    contentApiMocks.fetchUserMarkdownSpacePage.mockImplementation(
      () => new Promise(() => {}),
    );
    const queryClient = new QueryClient({
      defaultOptions: { queries: { retry: false, staleTime: Infinity } },
    });
    queryClient.setQueryData(queryKeys.userMarkdownSpaces("default"), {
      ok: true,
      summary: { spaceCount: 1 },
      spaces: [space],
    });
    queryClient.setQueryData(queryKeys.userMarkdownSpacePages("default", "space-1"), {
      ok: true,
      space,
      summary: { pageCount: 1 },
      pages: [page],
    });

    const container = renderPanel(queryClient);
    await flushEffects();
    await flushEffects();

    expect(contentApiMocks.fetchUserMarkdownSpacePage).toHaveBeenCalledWith("space-1", "page-1", { userId: "default" });
    expect(container.querySelector('[aria-label="正在读取页面"][aria-busy="true"]')).not.toBeNull();
  });
});
