import { afterEach, describe, expect, it, vi } from "vitest";

import {
  applySessionTurnRewind,
  isFetchJsonHttpError,
  previewSessionTurnRewind,
  sessionRewindUnsafeFilesFromError,
} from "./chat";
import { FetchJsonHttpError } from "./client";
import { seedControlTokenForTests } from "./client";

const PREVIEW_BODY = {
  sessionId: "sess-1",
  turnId: "turn-9",
  files: [
    { path: "web/src/a.ts", action: "restore", classification: "safe", state: "modified", currentExists: true, currentSize: 128 },
    { path: "notes/new.md", action: "delete", classification: "safe", state: "created", currentExists: true, currentSize: 16 },
    { path: "ext/edited.txt", action: "none", classification: "external_modified", state: "modified", currentExists: true, currentSize: 64 },
  ],
  canApply: false,
  capabilityNote: "1 个文件在本轮写入后被再次修改，默认拒绝整批回退。",
};

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  };
}

describe("session turn rewind transport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("fetches the per-turn rewind preview from the session route", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, PREVIEW_BODY));
    vi.stubGlobal("fetch", fetchMock);

    const preview = await previewSessionTurnRewind("sess/1", "turn/9");

    expect(preview.canApply).toBe(false);
    expect(preview.files).toHaveLength(3);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [endpoint, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/sessions/sess%2F1/rewind/turn%2F9");
    expect(init.method ?? "GET").toBe("GET");
  });

  it("posts strict apply by default and force only when asked", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      sessionId: "sess-1", turnId: "turn-9", status: "applied", alreadyApplied: false,
      applied: [{ path: "web/src/a.ts", action: "restore" }], skipped: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const applied = await applySessionTurnRewind("sess-1", { turnId: "turn-9" });
    expect(applied.alreadyApplied).toBe(false);
    expect(applied.applied).toEqual([{ path: "web/src/a.ts", action: "restore" }]);

    await applySessionTurnRewind("sess-1", { turnId: "turn-9", force: true });
    const bodies = fetchMock.mock.calls.map((call) => JSON.parse((call[1] as RequestInit).body as string));
    expect(bodies).toEqual([
      { turnId: "turn-9", force: false },
      { turnId: "turn-9", force: true },
    ]);
    const [endpoint, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/sessions/sess-1/rewind");
    expect(init.method).toBe("POST");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
  });

  it("maps a strict 409 conflict onto the unsafeFiles detail payload", async () => {
    seedControlTokenForTests();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(409, {
      detail: {
        message: "部分文件在本轮写入后被再次修改，已拒绝整批回退。",
        unsafeFiles: [
          { path: "ext/edited.txt", action: "none", classification: "external_modified", state: "modified", currentExists: true, currentSize: 64 },
        ],
      },
    })));

    const error = await applySessionTurnRewind("sess-1", { turnId: "turn-9" }).then(
      () => null,
      (failure: unknown) => failure,
    );
    expect(isFetchJsonHttpError(error)).toBe(true);
    expect((error as FetchJsonHttpError).status).toBe(409);
    expect(sessionRewindUnsafeFilesFromError(error)).toEqual([
      { path: "ext/edited.txt", classification: "external_modified" },
    ]);
  });

  it("tolerates flat and malformed conflict payloads without throwing", () => {
    const conflict = new FetchJsonHttpError("conflict", {
      status: 409,
      details: { unsafeFiles: ["flat/path.txt", { classification: "ignored" }, ""] },
    });
    expect(sessionRewindUnsafeFilesFromError(conflict)).toEqual([{ path: "flat/path.txt", classification: undefined }]);

    const noFiles = new FetchJsonHttpError("other", { status: 500, details: { detail: "boom" } });
    expect(sessionRewindUnsafeFilesFromError(noFiles)).toEqual([]);
    expect(sessionRewindUnsafeFilesFromError(new Error("network"))).toEqual([]);
  });
});
