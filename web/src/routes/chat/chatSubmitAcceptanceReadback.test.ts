import { QueryClient } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { SessionDetail } from "../../api/types";
import { readbackSubmitAcceptance } from "./chatSubmitAcceptanceReadback";
import { beginSessionSubmit, mergeSessionSubmitDetail } from "./sessionSubmitProjection";

const key = ["launcher-assistant", "detail", "s"];
const native = (ledgerSeq = 2): SessionDetail => ({ id: "s", ledgerSeq, messages: [{ id: "native", role: "user", content: "hello",
  timestamp: "", metadata: { clientSubmissionId: "request-1", turnId: "turn-1" } }] } as SessionDetail);
afterEach(() => vi.useRealTimers());

describe("submit acceptance with a role-scoped transport", () => {
  it("ignores optimistic paint as admission and reads through the injected key/reader", async () => {
    const client = new QueryClient();
    client.setQueryData(key, beginSessionSubmit({ id: "s", messages: [] } as unknown as SessionDetail,
      { sessionId: "s", clientSubmissionId: "request-1", content: "hello" }));
    const readDetail = vi.fn(async () => native());
    expect(await readbackSubmitAcceptance(client, "s", "request-1", { detailQueryKey: () => key, readDetail, mergeDetail: mergeSessionSubmitDetail }))
      .toEqual({ evidence: "canonical_message", status: "readback_confirmed" });
    expect(readDetail).toHaveBeenCalledTimes(1);
    expect(client.getQueryData<SessionDetail>(key)?.messages.map(row => row.id)).toEqual(["native"]);
    expect(client.getQueryData(["session", "s"])).toBeUndefined();
    client.clear();
  });

  it("rejects foreign session responses without writing either cache", async () => {
    const client = new QueryClient();
    const result = await readbackSubmitAcceptance(client, "s", "request-1", {
      detailQueryKey: () => key, readDetail: async () => ({ ...native(), id: "foreign" }),
    });
    expect(result.status).toBe("not_found"); expect(client.getQueryData(key)).toBeUndefined(); client.clear();
  });

  it("bounds an uninterruptible IPC read and never applies its late result", async () => {
    vi.useFakeTimers();
    const client = new QueryClient();
    let finish!: (value: SessionDetail) => void;
    const result = readbackSubmitAcceptance(client, "s", "request-1", {
      detailQueryKey: () => key, readDetail: () => new Promise(resolve => { finish = resolve; }),
    });
    await vi.advanceTimersByTimeAsync(3000);
    expect(await result).toEqual({ evidence: null, status: "readback_failed" });
    finish(native()); await Promise.resolve();
    expect(client.getQueryData(key)).toBeUndefined(); client.clear();
  });
});
