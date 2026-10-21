// @vitest-environment happy-dom
import { afterEach, describe, expect, it } from "vitest";
import { QueryClient } from "@tanstack/react-query";

import { queryKeys } from "../api/queryKeys";
import {
  applySessionIndexChangeToQueryClient,
  broadcastSessionIndexChange,
  parseSessionIndexChangeMessage,
  SESSION_INDEX_SYNC_STORAGE_KEY,
  subscribeSessionIndexChanges,
} from "./chatSessionIndexSync";
import type { SessionDetail } from "../api/types";

function makeDetail(sessionId: string): SessionDetail {
  return {
    id: sessionId,
    title: `会话 ${sessionId}`,
    status: "idle",
    taskSummary: "",
    lastActive: "2026-05-22T10:00:00Z",
    updatedAt: "2026-05-22T10:00:00Z",
    currentPhase: "idle",
    messages: [],
  } as SessionDetail;
}

afterEach(() => {
  window.localStorage.clear();
});

describe("chatSessionIndexSync", () => {
  it("broadcasts a parseable change message through localStorage", () => {
    broadcastSessionIndexChange({ sessionId: "session-1", changeType: "pin", sourceId: "page-writer" });
    const message = parseSessionIndexChangeMessage(window.localStorage.getItem(SESSION_INDEX_SYNC_STORAGE_KEY));
    expect(message).toMatchObject({
      sessionId: "session-1",
      changeType: "pin",
      sourceId: "page-writer",
    });
    // A second identical write still differs (storage events need a value change).
    broadcastSessionIndexChange({ sessionId: "session-1", changeType: "pin", sourceId: "page-writer", at: 42 });
    expect(parseSessionIndexChangeMessage(window.localStorage.getItem(SESSION_INDEX_SYNC_STORAGE_KEY)))
      .toMatchObject({ at: 42 });
    // Invalid sessions are never broadcast.
    broadcastSessionIndexChange({ sessionId: "", changeType: "pin", sourceId: "p" });
    expect(window.localStorage.getItem(SESSION_INDEX_SYNC_STORAGE_KEY)).toMatch(/"at":42/);
  });

  it("rejects malformed or foreign payloads when parsing", () => {
    expect(parseSessionIndexChangeMessage(null)).toBeNull();
    expect(parseSessionIndexChangeMessage("")).toBeNull();
    expect(parseSessionIndexChangeMessage("not json")).toBeNull();
    expect(parseSessionIndexChangeMessage(JSON.stringify({ sessionId: "s1" }))).toBeNull();
    expect(parseSessionIndexChangeMessage(JSON.stringify({ sessionId: "s1", changeType: "nope" }))).toBeNull();
    expect(
      parseSessionIndexChangeMessage(JSON.stringify({ sessionId: "s1", changeType: "unpin", sourceId: "p", at: 7 })),
    ).toEqual({ sessionId: "s1", changeType: "unpin", sourceId: "p", at: 7 });
  });

  it("notifies other windows on a matching storage event and dedupes self writes", () => {
    const received: string[] = [];
    const unsubscribe = subscribeSessionIndexChanges((message) => received.push(message.sessionId), {
      ownSourceId: "page-self",
    });
    const fire = (key: string | null, rawValue: string | null) => {
      window.dispatchEvent(new StorageEvent("storage", { key, newValue: rawValue }));
    };
    // Another window's pin write arrives.
    fire(
      SESSION_INDEX_SYNC_STORAGE_KEY,
      JSON.stringify({ sessionId: "s1", changeType: "pin", sourceId: "page-other", at: 1 }),
    );
    // Own write is deduplicated, foreign keys and garbage are ignored.
    fire(
      SESSION_INDEX_SYNC_STORAGE_KEY,
      JSON.stringify({ sessionId: "s2", changeType: "pin", sourceId: "page-self", at: 2 }),
    );
    fire("vibelution.workbench.theme", JSON.stringify({ sessionId: "s3", changeType: "pin", at: 3 }));
    fire(SESSION_INDEX_SYNC_STORAGE_KEY, "{broken");
    fire(SESSION_INDEX_SYNC_STORAGE_KEY, null);

    expect(received).toEqual(["s1"]);
    unsubscribe();
    fire(
      SESSION_INDEX_SYNC_STORAGE_KEY,
      JSON.stringify({ sessionId: "s4", changeType: "pin", sourceId: "page-other", at: 4 }),
    );
    expect(received).toEqual(["s1"]);
  });

  it("invalidates the sessions index query (and per-session detail by prefix)", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.sessionQuery(), [{ id: "s1" }]);
    queryClient.setQueryData(queryKeys.session("s1"), makeDetail("s1"));
    expect(queryClient.getQueryState(queryKeys.sessionQuery())?.isInvalidated).toBe(false);

    applySessionIndexChangeToQueryClient(queryClient, {
      sessionId: "s1",
      changeType: "pin",
      sourceId: "page-other",
      at: 1,
    });
    await Promise.resolve();
    expect(queryClient.getQueryState(queryKeys.sessionQuery())?.isInvalidated).toBe(true);
    expect(queryClient.getQueryState(queryKeys.session("s1"))?.isInvalidated).toBe(true);
    await queryClient.cancelQueries();
    queryClient.clear();
  });

  it("ignores messages without a session id", async () => {
    const queryClient = new QueryClient();
    queryClient.setQueryData(queryKeys.sessionQuery(), [{ id: "s1" }]);
    applySessionIndexChangeToQueryClient(queryClient, {
      sessionId: "",
      changeType: "pin",
      sourceId: "page-other",
      at: 1,
    });
    await Promise.resolve();
    expect(queryClient.getQueryState(queryKeys.sessionQuery())?.isInvalidated).toBe(false);
    await queryClient.cancelQueries();
    queryClient.clear();
  });
});
