import { afterEach, describe, expect, it, vi } from "vitest";
import continuationRequestSource from "../../../tests/fixtures/session_continuation_request.json?raw";
import { submitSessionMessage, type SessionContinuationExpectation } from "./chat";
import { seedControlTokenForTests } from "./client";

const continuationRequest = JSON.parse(continuationRequestSource) as {
  content: string;
  contentUtf8Base64: string;
  queueIfBusy: boolean;
  continuation: SessionContinuationExpectation;
};

function mockAcceptedTransport() {
  seedControlTokenForTests();
  const receipt = { accepted: true, sessionId: "session/continue", turnId: "new-turn" };
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true, status: 202,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => receipt,
  });
  vi.stubGlobal("fetch", fetchMock);
  return { fetchMock, receipt };
}

afterEach(() => { vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("native continuation submit transport", () => {
  it("serializes the shared continuation fixture through the existing message POST", async () => {
    const { fetchMock, receipt } = mockAcceptedTransport();
    const payload = {
      ...continuationRequest, clientSubmissionId: "continue-submission", attachmentIds: [], references: [],
    };
    expect(await submitSessionMessage("session/continue", payload)).toEqual(receipt);

    expect(fetchMock).toHaveBeenCalledOnce();
    const [endpoint, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/sessions/session%2Fcontinue/messages");
    expect(init.method).toBe("POST");
    expect((init.headers as Headers).get("Content-Type")).toBe("application/json");
    expect((init.headers as Headers).get("Prefer")).toBe("respond-async");
    const body = JSON.parse(init.body as string);
    expect(body).toEqual(payload);
    expect(body.continuation).toEqual(continuationRequest.continuation);
    expect(body.queueIfBusy).toBe(false);
    expect(body.content).toBe("继续");
    expect(Buffer.from(body.contentUtf8Base64, "base64").toString("utf8")).toBe(body.content);
  });

  it("keeps an ordinary submission free of optional continuation and queue fields", async () => {
    const { fetchMock } = mockAcceptedTransport();
    const payload = {
      content: "普通输入", contentUtf8Base64: Buffer.from("普通输入", "utf8").toString("base64"),
      clientSubmissionId: "normal-submission", attachmentIds: ["artifact-1"],
      references: [{ kind: "message", sourceMessageId: "message-1", quote: "引用" }],
    };
    await submitSessionMessage("normal-session", payload);
    const body = JSON.parse((fetchMock.mock.calls[0][1] as RequestInit).body as string);
    expect(body).toEqual(payload);
    expect(body).not.toHaveProperty("continuation");
    expect(body).not.toHaveProperty("queueIfBusy");
  });
});
