// @vitest-environment node
import { createServer } from "node:http";
import { expect, it, vi } from "vitest";

import { consumeGuardedEventStream } from "./guardedEventStream";

it("closes real HTTP streams after repeated frame callback failures", async () => {
  let activeResponses = 0;
  let openedResponses = 0;
  const server = createServer((_request, response) => {
    openedResponses += 1;
    activeResponses += 1;
    response.once("close", () => { activeResponses -= 1; });
    response.writeHead(200, { "Content-Type": "text/event-stream" });
    response.write("event: update\ndata: isolated transport probe\n\n");
  });
  await new Promise<void>((resolve, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolve);
  });
  try {
    const address = server.address();
    if (!address || typeof address === "string") throw new Error("Missing probe port");
    for (let attempt = 0; attempt < 2; attempt += 1) {
      const failure = new Error(`callback failed ${attempt}`);
      await expect(consumeGuardedEventStream({
        url: `http://127.0.0.1:${address.port}/events`,
        signal: new AbortController().signal,
        onFrame: () => { throw failure; },
      })).rejects.toBe(failure);
      await vi.waitFor(() => expect(activeResponses).toBe(0), { timeout: 1000 });
    }
    expect(openedResponses).toBe(2);
  } finally {
    server.closeAllConnections();
    await new Promise<void>((resolve, reject) => {
      server.close((error) => error ? reject(error) : resolve());
    });
  }
});
