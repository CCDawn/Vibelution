import { afterEach, describe, expect, it, vi } from "vitest";

import {
  archiveChatSession,
  listArchivedChatSessions,
  unarchiveChatSession,
} from "./sessionArchive";
import { seedControlTokenForTests } from "./client";

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  };
}

describe("session archive transport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("posts the archive command to the per-session archive route", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      sessionId: "sess/1",
      status: "archived",
      changed: true,
      archivedAt: "2026-09-29T00:00:00+00:00",
      readOnly: true,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await archiveChatSession("sess/1");

    expect(result.status).toBe("archived");
    expect(result.changed).toBe(true);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/sessions/sess%2F1/archive");
    expect(init?.method).toBe("POST");
  });

  it("posts the unarchive command to the per-session unarchive route", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      sessionId: "sess-1",
      status: "",
      changed: true,
      readOnly: false,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await unarchiveChatSession("sess-1");

    expect(result.changed).toBe(true);
    expect(result.readOnly).toBe(false);
    const [url, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/sessions/sess-1/unarchive");
    expect(init?.method).toBe("POST");
  });

  it("lists archived sessions from the dedicated archive route", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      items: [{ id: "sess-9", archiveState: { status: "archived" } }],
      nextCursor: "",
      totalEstimate: 1,
    }));
    vi.stubGlobal("fetch", fetchMock);

    const page = await listArchivedChatSessions({ limit: 50, cursor: "10" });

    expect(page.totalEstimate).toBe(1);
    expect(page.items[0]?.id).toBe("sess-9");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("/api/session-archive?limit=50&cursor=10");
  });

  it("omits the query suffix when paging defaults are used", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, { items: [], nextCursor: "", totalEstimate: 0 }));
    vi.stubGlobal("fetch", fetchMock);

    await listArchivedChatSessions();

    const [url] = fetchMock.mock.calls[0] as [string];
    expect(url).toBe("/api/session-archive");
  });
});
