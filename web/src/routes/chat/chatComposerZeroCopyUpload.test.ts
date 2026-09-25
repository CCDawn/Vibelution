import { afterEach, describe, expect, it, vi } from "vitest";

import { resetControlTokenForTests, seedControlTokenForTests } from "../../api/client";
import { uploadSessionImageAttachment, type ComposerImageAttachment } from "./chatComposerSubmitModel";

function makeAttachment(overrides: Partial<ComposerImageAttachment> = {}): ComposerImageAttachment {
  const file = new File([new Uint8Array([1, 2, 3])], "a.png", { type: "image/png" });
  return {
    id: "att-1",
    file,
    filename: "a.png",
    previewUrl: "blob:test",
    sizeBytes: file.size,
    contentType: "image/png",
    kind: "image",
    ...overrides,
  };
}

type RecordedCall = { input: string; init: RequestInit };

function stubFetch(responder: (call: RecordedCall, index: number) => Response) {
  const calls: RecordedCall[] = [];
  const fetchMock = vi.fn(async (input: unknown, init?: RequestInit) => {
    const call = { input: String(input), init: (init ?? {}) as RequestInit };
    calls.push(call);
    return responder(call, calls.length - 1);
  });
  vi.stubGlobal("fetch", fetchMock);
  return calls;
}

function jsonResponse(payload: unknown, status = 201) {
  return new Response(JSON.stringify(payload), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

function headerOf(init: RequestInit, name: string) {
  return new Headers(init.headers).get(name);
}

describe("zero-copy composer attachment upload", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
    resetControlTokenForTests();
  });

  it("registers attachments carrying a local path without uploading bytes", async () => {
    seedControlTokenForTests();
    const calls = stubFetch(() =>
      jsonResponse({ artifactId: "user-image-1", filename: "a.png", kind: "user_image", status: "ready" }),
    );

    const uploaded = await uploadSessionImageAttachment(
      "session-1",
      makeAttachment({ localPath: "C:\\pics\\a.png" }),
    );

    expect(uploaded.artifactId).toBe("user-image-1");
    expect(calls).toHaveLength(1);
    const { init } = calls[0];
    expect(calls[0].input).toBe("/api/sessions/session-1/attachments");
    expect(init.method).toBe("POST");
    expect(headerOf(init, "Content-Type")).toBe("application/json");
    expect(JSON.parse(String(init.body))).toEqual({
      localPath: "C:\\pics\\a.png",
      contentType: "image/png",
      filename: "a.png",
    });
  });

  it("falls back to the binary upload when zero-copy registration fails", async () => {
    seedControlTokenForTests();
    const calls = stubFetch((_call, index) =>
      index === 0
        ? jsonResponse({ detail: "Attachment path does not exist: a.png" }, 404)
        : jsonResponse({ artifactId: "user-image-2", filename: "a.png", kind: "user_image", status: "ready" }),
    );

    const attachment = makeAttachment({ localPath: "C:\\pics\\missing.png" });
    const uploaded = await uploadSessionImageAttachment("session-1", attachment);

    expect(uploaded.artifactId).toBe("user-image-2");
    expect(calls).toHaveLength(2);
    expect(headerOf(calls[0].init, "Content-Type")).toBe("application/json");
    expect(headerOf(calls[1].init, "Content-Type")).toBe("image/png");
    expect(headerOf(calls[1].init, "X-Vibelution-Filename")).toBe(encodeURIComponent("a.png"));
    expect(calls[1].init.body).toBe(attachment.file);
  });

  it("keeps the plain binary upload for attachments without a local path", async () => {
    seedControlTokenForTests();
    const calls = stubFetch(() =>
      jsonResponse({ artifactId: "user-image-3", filename: "a.png", kind: "user_image", status: "ready" }),
    );

    const attachment = makeAttachment();
    const uploaded = await uploadSessionImageAttachment("session-1", attachment);

    expect(uploaded.artifactId).toBe("user-image-3");
    expect(calls).toHaveLength(1);
    expect(headerOf(calls[0].init, "Content-Type")).toBe("image/png");
    expect(calls[0].init.body).toBe(attachment.file);
  });
});
