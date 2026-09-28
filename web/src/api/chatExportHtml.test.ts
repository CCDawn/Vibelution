import { afterEach, describe, expect, it, vi } from "vitest";

import { exportSessionHtml } from "./chat";
import { FetchJsonHttpError, seedControlTokenForTests } from "./client";

function jsonResponse(status: number, body: unknown) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: new Headers({ "content-type": "application/json" }),
    json: async () => body,
  };
}

describe("session export-html transport", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("posts the export request and returns the document payload", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      filename: "vibelution-demo-20260928.html",
      html: "<!doctype html><html lang=\"zh\"></html>",
      skippedTurnIds: ["ghost"],
    }));
    vi.stubGlobal("fetch", fetchMock);

    const result = await exportSessionHtml("sess/1", {
      turnIds: ["turn-1", "ghost"],
      includeAttachments: false,
    });

    expect(result.filename).toBe("vibelution-demo-20260928.html");
    expect(result.skippedTurnIds).toEqual(["ghost"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [endpoint, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(endpoint).toBe("/api/sessions/sess%2F1/export-html");
    expect(init.method).toBe("POST");
    expect(JSON.parse(init.body as string)).toEqual({
      turnIds: ["turn-1", "ghost"],
      includeAttachments: false,
    });
  });

  it("defaults to every turn with attachments embedded", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(200, {
      filename: "vibelution-session.html",
      html: "<!doctype html>",
      skippedTurnIds: [],
    }));
    vi.stubGlobal("fetch", fetchMock);

    await exportSessionHtml("sess-1");

    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(init.body as string)).toEqual({
      turnIds: [],
      includeAttachments: true,
    });
  });

  it("propagates HTTP errors (404 missing session)", async () => {
    seedControlTokenForTests();
    const fetchMock = vi.fn().mockResolvedValue(jsonResponse(404, { detail: "Session not found" }));
    vi.stubGlobal("fetch", fetchMock);

    await expect(exportSessionHtml("missing")).rejects.toMatchObject({
      status: 404,
    });
    try {
      await exportSessionHtml("missing");
    } catch (error) {
      expect(error).toBeInstanceOf(FetchJsonHttpError);
    }
  });
});
