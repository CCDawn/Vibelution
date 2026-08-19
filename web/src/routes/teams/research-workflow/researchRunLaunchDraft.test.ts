import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  clearResearchRunLaunchDraft,
  readResearchRunLaunchDraft,
  writeResearchRunLaunchDraft,
} from "./researchRunLaunchDraft";
import { createResearchRunSafetyBudget } from "./researchRunSafetyBudget";

function stubSessionStorage() {
  const store = new Map<string, string>();
  const storage = {
    getItem: (key: string) => (store.has(key) ? store.get(key)! : null),
    setItem: (key: string, value: string) => {
      store.set(key, String(value));
    },
    removeItem: (key: string) => {
      store.delete(key);
    },
    clear: () => store.clear(),
  };
  vi.stubGlobal("window", { sessionStorage: storage });
  return storage;
}

describe("research run launch draft", () => {
  beforeEach(() => {
    stubSessionStorage();
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("round-trips question, query, and safety budget per team", () => {
    const safetyBudget = {
      ...createResearchRunSafetyBudget(),
      toolCalls: 123,
    };
    writeResearchRunLaunchDraft("team-a", {
      questionId: "SCI-003",
      query: "Riemann",
      safetyBudget,
    });
    expect(readResearchRunLaunchDraft("team-a")).toEqual({
      questionId: "SCI-003",
      query: "Riemann",
      safetyBudget,
    });
    // Another team must not see team-a's draft.
    expect(readResearchRunLaunchDraft("team-b")).toBeNull();
  });

  it("returns null for missing, empty, or corrupt drafts", () => {
    expect(readResearchRunLaunchDraft("")).toBeNull();
    expect(readResearchRunLaunchDraft("team-missing")).toBeNull();
    window.sessionStorage.setItem("vibelution.research-run-launch.team-x", "{not json");
    expect(readResearchRunLaunchDraft("team-x")).toBeNull();
    window.sessionStorage.setItem("vibelution.research-run-launch.team-null", "null");
    expect(readResearchRunLaunchDraft("team-null")).toBeNull();
  });

  it("normalizes corrupt fields instead of crashing", () => {
    window.sessionStorage.setItem(
      "vibelution.research-run-launch.team-y",
      JSON.stringify({
        questionId: 42,
        query: null,
        safetyBudget: {
          stageTokens: { knowledge_collection: -5, experiment_design: "bad" },
          toolCalls: 0,
          wallClockSeconds: "bad",
        },
      }),
    );
    const fallback = createResearchRunSafetyBudget();
    expect(readResearchRunLaunchDraft("team-y")).toEqual({
      questionId: "",
      query: "",
      safetyBudget: {
        stageTokens: {
          knowledge_collection: fallback.stageTokens.knowledge_collection,
          experiment_design: fallback.stageTokens.experiment_design,
          execution_iteration: fallback.stageTokens.execution_iteration,
        },
        toolCalls: fallback.toolCalls,
        wallClockSeconds: fallback.wallClockSeconds,
        maxRetries: fallback.maxRetries,
      },
    });
  });

  it("keeps valid custom safety budget values", () => {
    window.sessionStorage.setItem(
      "vibelution.research-run-launch.team-z",
      JSON.stringify({
        questionId: "SCI-091",
        query: "",
        safetyBudget: {
          stageTokens: {
            knowledge_collection: 111,
            experiment_design: 222,
            execution_iteration: 333,
          },
          toolCalls: 44,
          wallClockSeconds: 5555,
          maxRetries: 3,
        },
      }),
    );
    expect(readResearchRunLaunchDraft("team-z")?.safetyBudget).toEqual({
      stageTokens: {
        knowledge_collection: 111,
        experiment_design: 222,
        execution_iteration: 333,
      },
      toolCalls: 44,
      wallClockSeconds: 5555,
      maxRetries: 3,
    });
  });

  it("clears the team draft", () => {
    writeResearchRunLaunchDraft("team-a", {
      questionId: "SCI-003",
      query: "",
      safetyBudget: createResearchRunSafetyBudget(),
    });
    clearResearchRunLaunchDraft("team-a");
    expect(readResearchRunLaunchDraft("team-a")).toBeNull();
  });

  it("degrades to no-op when window/sessionStorage is unavailable", () => {
    vi.unstubAllGlobals();
    expect(readResearchRunLaunchDraft("team-a")).toBeNull();
    expect(() =>
      writeResearchRunLaunchDraft("team-a", {
        questionId: "SCI-003",
        query: "",
        safetyBudget: createResearchRunSafetyBudget(),
      }),
    ).not.toThrow();
    expect(() => clearResearchRunLaunchDraft("team-a")).not.toThrow();
  });
});
