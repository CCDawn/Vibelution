import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { seedControlTokenForTests } from "./client";
import {
  DEFAULT_RUNTIME_TASK_PAGE_LIMIT,
  childSessionHref,
  listRuntimeTasksRevisionAware,
  runtimeTaskDetailUrl,
  runtimeTasksListUrl,
  stopRuntimeTask,
  type RuntimeTaskListPayload,
} from "./runtimeTasks";

function payloadWith(revision: string): RuntimeTaskListPayload {
  return {
    revision,
    running: [],
    ended: { items: [], total: 0, nextCursor: "" },
  };
}

function jsonResponse(body: unknown) {
  return new Response(JSON.stringify(body), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

describe("runtimeTasks api", () => {
  beforeEach(() => {
    seedControlTokenForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  it("builds list URLs with status, kind, parent session, cursor and limit", () => {
    expect(runtimeTasksListUrl()).toBe(
      `/api/runtime-tasks?status=all&limit=${DEFAULT_RUNTIME_TASK_PAGE_LIMIT}`,
    );
    expect(
      runtimeTasksListUrl({
        status: "ended",
        kind: "cli_agent",
        parentSessionId: "parent 1",
        cursor: "cur-2",
        limit: 20,
      }),
    ).toBe("/api/runtime-tasks?status=ended&kind=cli_agent&parent_session_id=parent+1&cursor=cur-2&limit=20");
  });

  it("encodes the task id in detail URLs", () => {
    expect(runtimeTaskDetailUrl("task/1")).toBe("/api/runtime-tasks/task%2F1");
  });

  it("encodes child session ids into chat workbench links", () => {
    expect(childSessionHref("child 1")).toBe("/chat?session=child%201");
    expect(childSessionHref("  ")).toBe("");
  });

  it("posts the user stop intent to the stop endpoint", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      jsonResponse({ accepted: true, taskId: "task-1", status: "stopping" }),
    );
    vi.stubGlobal("fetch", fetchMock);
    const result = await stopRuntimeTask("task-1");
    expect(result.accepted).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toBe("/api/runtime-tasks/task-1/stop");
    expect(init?.method).toBe("POST");
    expect(String(init?.body)).toContain('"initiator":"user"');
  });

  it("keeps the previous payload object when the revision is unchanged", async () => {
    const previous = payloadWith("rev-7");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(payloadWith("rev-7")));
    vi.stubGlobal("fetch", fetchMock);
    const next = await listRuntimeTasksRevisionAware({}, previous);
    expect(next).toBe(previous);
  });

  it("returns the fresh payload when the revision advances", async () => {
    const previous = payloadWith("rev-7");
    const fresh = payloadWith("rev-8");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(fresh));
    vi.stubGlobal("fetch", fetchMock);
    const next = await listRuntimeTasksRevisionAware({}, previous);
    // fetchJson re-parses the body, so identity is fresh: the revision wrapper
    // only guarantees the previous object is dropped, never reused.
    expect(next).not.toBe(previous);
    expect(next).toEqual(fresh);
  });

  it("passes through the first payload when there is no cached previous", async () => {
    const fresh = payloadWith("rev-1");
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(fresh));
    vi.stubGlobal("fetch", fetchMock);
    const next = await listRuntimeTasksRevisionAware({}, undefined);
    expect(next).toEqual(fresh);
  });
});
