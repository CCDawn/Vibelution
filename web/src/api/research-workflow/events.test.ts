import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../client";
import type { WorkflowEventEnvelope } from "../types/research-workflow/events";
import {
  consumeResearchWorkflowEventStream,
  parseResearchWorkflowSseFrame,
  replayResearchWorkflowEvents,
} from "./events";

function envelope(sequence: number): WorkflowEventEnvelope {
  return {
    eventId: `evt-${sequence}`,
    sequence,
    runId: "run-a",
    teamId: "research-team",
    runVersion: sequence,
    type: sequence === 1 ? "run_created" : "node_starting",
    correlationId: "corr",
    occurredAt: "2026-08-12T14:00:00.000Z",
    payload: sequence === 1 ? {} : { nodeId: "source_finding", attempt: 1 },
  };
}

describe("replayResearchWorkflowEvents", () => {
  beforeEach(() => {
    resetControlTokenForTests();
    seedControlTokenForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("follows EventPage cursors until hasMore is false", async () => {
    const fetchMock = vi.fn(async (input: RequestInfo) => {
      const url = String(input);
      if (url.includes("afterSequence=0")) {
        return {
          ok: true,
          json: async () => ({
            runId: "run-a",
            teamId: "research-team",
            runVersion: 1,
            latestEventSequence: 3,
            afterSequence: 0,
            lastReturnedSequence: 2,
            hasMore: true,
            nextAfterSequence: 2,
            events: [envelope(1), envelope(2)],
          }),
        };
      }
      return {
        ok: true,
        json: async () => ({
          runId: "run-a",
          teamId: "research-team",
          runVersion: 1,
          latestEventSequence: 3,
          afterSequence: 2,
          lastReturnedSequence: 3,
          hasMore: false,
          nextAfterSequence: null,
          events: [envelope(3)],
        }),
      };
    });
    vi.stubGlobal("fetch", fetchMock);

    const events = await replayResearchWorkflowEvents({
      runId: "run-a",
      teamId: "research-team",
    });
    expect(events.map((item) => item.sequence)).toEqual([1, 2, 3]);
    expect(fetchMock).toHaveBeenCalledTimes(2);
    for (const [, init] of fetchMock.mock.calls) {
      expect(new Headers(init?.headers).get("X-Vibelution-Control-Token")).toBe(
        "test-control-token",
      );
    }
  });

  it("fails closed when the replay cursor does not advance", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => ({
      ok: true,
      json: async () => ({
        runId: "run-a",
        teamId: "research-team",
        runVersion: 1,
        latestEventSequence: 9,
        afterSequence: 0,
        lastReturnedSequence: 0,
        hasMore: true,
        nextAfterSequence: 0,
        events: [],
      }),
    })));

    await expect(
      replayResearchWorkflowEvents({ runId: "run-a", teamId: "research-team" }),
    ).rejects.toThrow("events_replay_cursor_stuck");
  });
});

describe("research workflow authenticated SSE", () => {
  beforeEach(() => {
    resetControlTokenForTests();
    seedControlTokenForTests();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("parses CRLF, multiline data, and ignores keepalive comments", () => {
    expect(parseResearchWorkflowSseFrame(": keepalive")).toBeNull();
    expect(
      parseResearchWorkflowSseFrame(
        "id: run-a:3\r\nevent: node_running\r\ndata: {\"sequence\":\r\ndata: 3}\r\n",
      ),
    ).toEqual({
      id: "run-a:3",
      event: "node_running",
      data: "{\"sequence\":\n3}",
    });
  });

  it("streams cross-chunk frames with a guarded header and Last-Event-ID", async () => {
    const encoder = new TextEncoder();
    const body = new ReadableStream<Uint8Array>({
      start(controller) {
        controller.enqueue(encoder.encode(": keepalive\n\nid: run-a:4\nevent: node_"));
        controller.enqueue(encoder.encode("running\ndata: {\"sequence\":4}\n\npartial"));
        controller.close();
      },
    });
    const fetchMock = vi.fn(async () => new Response(body, {
      headers: { "Content-Type": "text/event-stream" },
    }));
    vi.stubGlobal("fetch", fetchMock);
    const frames: unknown[] = [];
    const opened = vi.fn();

    await consumeResearchWorkflowEventStream({
      runId: "run-a",
      teamId: "research-team",
      afterSequence: 3,
      lastEventId: "run-a:3",
      signal: new AbortController().signal,
      onOpen: opened,
      onFrame: (frame) => frames.push(frame),
    });

    expect(opened).toHaveBeenCalledTimes(1);
    expect(frames).toEqual([
      { id: "run-a:4", event: "node_running", data: "{\"sequence\":4}" },
    ]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0];
    expect(String(url)).toContain("afterSequence=3");
    expect(String(url)).not.toContain("controlToken");
    const headers = new Headers(init?.headers);
    expect(headers.get("X-Vibelution-Control-Token")).toBe("test-control-token");
    expect(headers.get("Last-Event-ID")).toBe("run-a:3");
  });

  it("aborts a live reader without emitting a partial frame", async () => {
    const controller = new AbortController();
    let streamController: ReadableStreamDefaultController<Uint8Array> | null = null;
    const body = new ReadableStream<Uint8Array>({
      start(current) {
        streamController = current;
        current.enqueue(new TextEncoder().encode("id: run-a:1\nevent: run_created\ndata: {"));
      },
      cancel() {
        streamController = null;
      },
    });
    vi.stubGlobal("fetch", vi.fn(async (_input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.signal?.aborted) throw new DOMException("aborted", "AbortError");
      init?.signal?.addEventListener("abort", () => streamController?.error(new DOMException("aborted", "AbortError")));
      return new Response(body, { headers: { "Content-Type": "text/event-stream" } });
    }));
    const onFrame = vi.fn();
    const consuming = consumeResearchWorkflowEventStream({
      runId: "run-a",
      teamId: "research-team",
      afterSequence: 0,
      signal: controller.signal,
      onFrame,
    });

    controller.abort();

    await expect(consuming).rejects.toMatchObject({ name: "AbortError" });
    expect(onFrame).not.toHaveBeenCalled();
  });
});
