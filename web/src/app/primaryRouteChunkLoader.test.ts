import { describe, expect, it, vi } from "vitest";

import { loadPrimaryRouteChunk } from "./primaryRouteChunkLoader";

describe("loadPrimaryRouteChunk", () => {
  it("executes the lazy route loader returned by the router resolver", async () => {
    const routeModule = { default: "teams-route" };
    const loadChunk = vi.fn().mockResolvedValue(routeModule);
    const resolveRouteChunkLoader = vi.fn().mockResolvedValue(loadChunk);

    await expect(loadPrimaryRouteChunk(resolveRouteChunkLoader)).resolves.toBe(routeModule);

    expect(resolveRouteChunkLoader).toHaveBeenCalledOnce();
    expect(loadChunk).toHaveBeenCalledOnce();
  });

  it("propagates a rejected route chunk import", async () => {
    const failure = new Error("route chunk failed");
    const loadChunk = vi.fn().mockRejectedValue(failure);
    const resolveRouteChunkLoader = vi.fn().mockResolvedValue(loadChunk);

    await expect(loadPrimaryRouteChunk(resolveRouteChunkLoader)).rejects.toBe(failure);
    expect(loadChunk).toHaveBeenCalledOnce();
  });
});
