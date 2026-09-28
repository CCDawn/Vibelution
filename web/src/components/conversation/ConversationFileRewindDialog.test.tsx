/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import { clearControlToken, seedControlTokenForTests } from "../../api/client";
import { ConversationFileRewindDialog } from "./ConversationFileRewindDialog";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

const PREVIEW = {
  sessionId: "sess-1",
  turnId: "turn-9",
  files: [
    { path: "web/src/a.ts", action: "restore", classification: "safe", state: "modified", currentExists: true, currentSize: 2048 },
    { path: "notes/new.md", action: "delete", classification: "safe", state: "created", currentExists: true, currentSize: 16 },
    { path: "ext/edited.txt", action: "none", classification: "external_modified", state: "modified", currentExists: true, currentSize: 64 },
  ],
  canApply: false,
  capabilityNote: "1 个文件在本轮写入后被再次修改，默认拒绝整批回退。",
};

const APPLY_RESULT = {
  sessionId: "sess-1", turnId: "turn-9", status: "applied", alreadyApplied: false,
  applied: PREVIEW.files.map((file) => ({ path: file.path, action: file.action })),
  skipped: [],
};

function jsonResponse(status: number, payload: unknown) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function textContent(): string {
  return document.body.textContent ?? "";
}

function buttonByText(text: string): HTMLButtonElement | null {
  return Array.from(document.querySelectorAll("button"))
    .find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

async function waitFor(predicate: () => boolean, message: string) {
  for (let attempt = 0; attempt < 200 && !predicate(); attempt += 1) {
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 10));
    });
  }
  expect(predicate(), message).toBe(true);
}

type FetchRouter = (input: RequestInfo | URL, init?: RequestInit) => Promise<Response>;

describe("ConversationFileRewindDialog", () => {
  let root: Root | null = null;
  let fetchMock: ReturnType<typeof vi.fn> | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => {
        root?.unmount();
      });
    }
    document.body.innerHTML = "";
    root = null;
    fetchMock = null;
    clearControlToken();
    vi.unstubAllGlobals();
  });

  async function mount(router: FetchRouter) {
    fetchMock = vi.fn(router);
    vi.stubGlobal("fetch", fetchMock);
    seedControlTokenForTests();
    await act(async () => {
      root = createRoot(document.body);
      root.render(
        <ConversationFileRewindDialog
          open
          sessionId="sess-1"
          turnId="turn-9"
          language="zh"
          onOpenChange={() => undefined}
        />,
      );
    });
  }

  /** Rewind routes: GET `.../rewind/{turnId}` previews, POST `.../rewind` applies. */
  function rewindRouter(preview: FetchRouter | Response, apply: FetchRouter | Response): FetchRouter {
    const resolve = (candidate: FetchRouter | Response, input: RequestInfo | URL, init?: RequestInit) =>
      typeof candidate === "function" ? candidate(input, init) : Promise.resolve(candidate);
    return (input, init) => (init?.method === "POST"
      ? resolve(apply, input, init)
      : resolve(preview, input, init));
  }

  function postedBodies(): Array<Record<string, unknown>> {
    return (fetchMock?.mock.calls ?? [])
      .filter((call) => (call[1] as RequestInit | undefined)?.method === "POST")
      .map((call) => JSON.parse((call[1] as RequestInit).body as string));
  }

  it("loads the preview, renders per-file classifications and keeps the strict confirm", async () => {
    await mount(rewindRouter(jsonResponse(200, PREVIEW), jsonResponse(200, APPLY_RESULT)));
    await waitFor(() => textContent().includes("web/src/a.ts"), "preview rows render");
    const text = textContent();
    expect(text).toContain("可恢复");
    expect(text).toContain("写入后被其他程序修改");
    expect(text).toContain("将恢复写入前内容");
    expect(text).toContain("2.0 KB");
    expect(text).toContain("1 个文件在本轮写入后被再次修改");
    await act(async () => {
      buttonByText("回退本轮文件")!.click();
    });
    await waitFor(() => postedBodies().length === 1, "strict apply posted");
    expect(postedBodies()[0]).toEqual({ turnId: "turn-9", force: false });
    await waitFor(() => textContent().includes("已恢复 3 个文件；跳过 0 个。"), "result feedback");
    expect(buttonByText("仍恢复安全文件")).toBeNull();
  });

  it("surfaces the 409 unsafeFiles detail and falls back to the force escape hatch", async () => {
    let applyCount = 0;
    await mount(rewindRouter(
      jsonResponse(200, PREVIEW),
      () => {
        applyCount += 1;
        return Promise.resolve(applyCount === 1
          ? jsonResponse(409, {
            detail: {
              message: "部分文件在本轮写入后被再次修改，已拒绝整批回退。",
              unsafeFiles: [{ path: "ext/edited.txt", classification: "external_modified" }],
            },
          })
          : jsonResponse(200, APPLY_RESULT));
      },
    ));
    await waitFor(() => textContent().includes("web/src/a.ts"), "preview rows render");
    await act(async () => {
      buttonByText("回退本轮文件")!.click();
    });
    await waitFor(() => textContent().includes("整批回退已被拒绝"), "conflict section renders");
    expect(textContent().includes("ext/edited.txt")).toBe(true);
    const forceButton = buttonByText("仍恢复安全文件");
    expect(forceButton).not.toBeNull();
    await act(async () => {
      forceButton!.click();
    });
    await waitFor(() => postedBodies().length === 2, "force apply posted");
    expect(postedBodies()[1]).toEqual({ turnId: "turn-9", force: true });
    await waitFor(() => textContent().includes("已恢复 3 个文件"), "result feedback after force");
  });

  it("reports an idempotent replay instead of fabricated counts", async () => {
    await mount(rewindRouter(jsonResponse(200, PREVIEW), jsonResponse(200, {
      sessionId: "sess-1", turnId: "turn-9", status: "replayed", alreadyApplied: true,
      applied: [], skipped: [],
    })));
    await waitFor(() => textContent().includes("web/src/a.ts"), "preview rows render");
    await act(async () => {
      buttonByText("回退本轮文件")!.click();
    });
    await waitFor(() => textContent().includes("此前已恢复过"), "already-applied feedback");
    expect(textContent().includes("已恢复 0 个文件")).toBe(false);
  });

  it("keeps a friendly failure state with retry when the preview is missing", async () => {
    let missing = true;
    await mount(rewindRouter(
      () => Promise.resolve(jsonResponse(missing ? 404 : 200, missing
        ? { detail: "该轮次没有可回退的文件检查点。" }
        : PREVIEW)),
      jsonResponse(200, APPLY_RESULT),
    ));
    await waitFor(() => textContent().includes("该轮次没有可回退的文件检查点。"), "404 renders as plain text");
    missing = false;
    await act(async () => {
      buttonByText("重试")!.click();
    });
    await waitFor(() => textContent().includes("web/src/a.ts"), "retry loads the preview");
    expect(buttonByText("回退本轮文件")).not.toBeNull();
  });
});
