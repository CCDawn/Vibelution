import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "./client";
import { queryConversations, querySessions } from "./chat";
import { fetchRuntimeSummary } from "./runtime";

vi.mock("./client", () => ({ fetchJson: vi.fn().mockResolvedValue({}) }));

describe("navigation read cancellation transports", () => {
  beforeEach(() => vi.clearAllMocks());

  it("forwards cancellation without changing session filters", async () => {
    const signal = new AbortController().signal;
    await querySessions({ limit: 50, cursor: "next page", q: "hello", agentId: "a/b" }, { signal });
    expect(fetchJson).toHaveBeenCalledWith(
      "/api/sessions/query?limit=50&cursor=next+page&q=hello&agentId=a%2Fb",
      { signal },
    );
  });

  it("forwards cancellation without changing the group-room catalog request", async () => {
    const signal = new AbortController().signal;
    await queryConversations({ limit: 100, type: "group_room" }, { signal });
    expect(fetchJson).toHaveBeenCalledWith("/api/conversations?limit=100&type=group_room", { signal });
  });

  it("forwards cancellation to the shared runtime read", async () => {
    const signal = new AbortController().signal;
    await fetchRuntimeSummary({ signal });
    expect(fetchJson).toHaveBeenCalledWith("/api/runtime/summary", { signal });
  });
});
