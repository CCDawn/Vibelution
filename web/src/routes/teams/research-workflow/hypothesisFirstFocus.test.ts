import { describe, expect, it, vi } from "vitest";

import {
  fetchCollectionRequests,
  fetchHypothesisFirstChainState,
  fetchHypothesisSelections,
  fetchMeetingRounds,
} from "../../../api/hypothesisFirst";
import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";

vi.mock("../../../api/hypothesisFirst", () => ({
  fetchHypothesisFirstChainState: vi.fn(),
  fetchMeetingRounds: vi.fn(),
  fetchHypothesisSelections: vi.fn(),
  fetchCollectionRequests: vi.fn(),
}));

const mockedState = vi.mocked(fetchHypothesisFirstChainState);
const mockedMeetings = vi.mocked(fetchMeetingRounds);
const mockedSelections = vi.mocked(fetchHypothesisSelections);
const mockedRequests = vi.mocked(fetchCollectionRequests);

describe("fetchHypothesisFirstFocusNode", () => {
  it("lands on generation when a candidate-generation meeting is open", async () => {
    mockedState.mockResolvedValue({ candidateCount: 0 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "open",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_generation");
  });

  it("lands on selection when candidates exist and none are chosen", async () => {
    mockedState.mockResolvedValue({ candidateCount: 2 } as never);
    mockedMeetings.mockResolvedValue({
      meetings: [{
        question: "SCI-002",
        meetingType: "hypothesis_candidate_generation",
        status: "closed",
        meetingRoundId: "gen-1",
        startedAt: "2026-08-19T00:00:00Z",
      }],
    } as never);
    mockedSelections.mockResolvedValue({ selections: [] } as never);
    mockedRequests.mockResolvedValue({ requests: [] } as never);

    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_selection");
  });

  it("falls back to generation when the chain cannot be read", async () => {
    mockedState.mockRejectedValue(new Error("offline"));
    mockedMeetings.mockRejectedValue(new Error("offline"));
    mockedSelections.mockRejectedValue(new Error("offline"));
    mockedRequests.mockRejectedValue(new Error("offline"));
    await expect(fetchHypothesisFirstFocusNode("team-1", "SCI-002")).resolves.toBe("hf_generation");
  });
});
