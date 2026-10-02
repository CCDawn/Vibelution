import { beforeEach, describe, expect, it, vi } from "vitest";

import { fetchJson } from "./client";
import { fetchEvolutionWorkbench, fetchEvolutionWorkspaceSnapshot, fetchSelfEvolutionWorkspaceSnapshot } from "./evolution";

vi.mock("./client", () => ({ fetchJson: vi.fn().mockResolvedValue({}) }));

describe("evolution route read cancellation", () => {
  beforeEach(() => vi.clearAllMocks());

  it.each([
    [fetchEvolutionWorkspaceSnapshot, "/api/evolution/workspace-snapshot"],
    [fetchEvolutionWorkbench, "/api/evolution/workbench"],
    [fetchSelfEvolutionWorkspaceSnapshot, "/api/evolution/self/workspace-snapshot"],
  ] as const)("keeps the snapshot URL and passes its cancellation signal", async (read, endpoint) => {
    const signal = new AbortController().signal;
    await read({ signal });
    expect(fetchJson).toHaveBeenCalledWith(endpoint, { signal });
  });
});
