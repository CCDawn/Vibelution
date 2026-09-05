import { beforeEach, describe, expect, it, vi } from "vitest";
import { fetchHypothesisFirstStateV2 } from "../../../api/hypothesisFirst";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import { command, stateV2 } from "./hypothesisFirstV2.fixture";
vi.mock("../../../api/hypothesisFirst", async (importOriginal) => ({ ...await importOriginal<typeof import("../../../api/hypothesisFirst")>(), fetchHypothesisFirstStateV2: vi.fn() }));
beforeEach(() => vi.resetAllMocks());
describe("V2 current task focus", () => {
  it("reads the selected run and uses the canonical task", async () => {
    vi.mocked(fetchHypothesisFirstStateV2).mockResolvedValue(stateV2({allowedActions: [command({command: "open_generation", payload: {}})]}));
    expect(await fetchHypothesisFirstFocusNode(" team-1 ", " Q-01 ", " run-1 ")).toBe("hf_generation");
    expect(fetchHypothesisFirstStateV2).toHaveBeenCalledWith("team-1", "Q-01", {runId: "run-1"});
  });
  it.each([404, 500])("surfaces HTTP %s without reading an old endpoint", async (status) => {
    vi.mocked(fetchHypothesisFirstStateV2).mockRejectedValue(Object.assign(new Error("state unavailable"), {status}));
    await expect(fetchHypothesisFirstFocusNode("team-1", "Q-01")).rejects.toThrow("state unavailable");
  });
  it("surfaces fatal domain problems", async () => {
    vi.mocked(fetchHypothesisFirstStateV2).mockResolvedValue(stateV2({problems: [{severity: "fatal", message: "scope rejected"}]}));
    await expect(fetchHypothesisFirstFocusNode("team-1", "Q-01")).rejects.toThrow("scope rejected");
  });
});
