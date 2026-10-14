import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import type { SessionLlmModelOption } from "../../api/types";
import {
  displayedComposerEffort,
  groupComposerModelChoices,
  normalizeStoredComposerModelSelection,
  resolveComposerEffortForModel,
  selectionAfterModelPick,
} from "./composerModelEffort";

const luna: SessionLlmModelOption = {
  modelId: "ai-pixel/luna",
  modelRef: "ai-pixel/luna",
  label: "Luna 5.6",
  model: "luna",
  providerId: "ai-pixel",
  providerLabel: "Ai-Pixel",
  providerKind: "relay",
  apiKeyConfigured: true,
  missingApiKey: false,
  supportsReasoningEffort: true,
  reasoningEffortValues: ["low", "high"],
  reasoningEffortOptions: [],
  defaultReasoningEffort: "low",
  isDefault: true,
};

const sol: SessionLlmModelOption = {
  ...luna,
  modelId: "ai-pixel/sol",
  modelRef: "ai-pixel/sol",
  label: "Sol 4",
  supportsReasoningEffort: true,
  reasoningEffortValues: ["low", "medium", "high"],
  defaultReasoningEffort: "medium",
  isDefault: false,
};

const terra: SessionLlmModelOption = {
  ...luna,
  modelId: "other/terra",
  modelRef: "other/terra",
  label: "Terra",
  providerId: "other",
  providerLabel: "Other",
  supportsReasoningEffort: false,
  reasoningEffortValues: [],
  defaultReasoningEffort: "",
  isDefault: false,
};

const choices = [luna, sol, terra];

describe("composerModelEffort", () => {
  it("keeps a level the next model supports and otherwise uses that model's default", () => {
    expect(resolveComposerEffortForModel("high", sol)).toBe("high");
    expect(resolveComposerEffortForModel("xhigh", sol)).toBe("medium");
    expect(resolveComposerEffortForModel("high", terra)).toBe("");
  });

  it("pins the carried level when the picked model is not the session default", () => {
    expect(selectionAfterModelPick({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "high",
      previousSelection: null,
      previousModel: luna,
      next: { modelId: sol.modelRef },
      choices,
    })).toEqual({ modelId: sol.modelRef, reasoningEffort: "high" });
  });

  it("clears the pin when the picked model is the session default", () => {
    expect(selectionAfterModelPick({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "low",
      previousSelection: { modelId: sol.modelRef, reasoningEffort: "medium" },
      previousModel: sol,
      next: { modelId: luna.modelRef },
      choices,
    })).toBeNull();
  });

  it("omits a level when the picked model cannot tune thinking", () => {
    expect(selectionAfterModelPick({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "high",
      previousSelection: null,
      previousModel: luna,
      next: { modelId: terra.modelRef },
      choices,
    })).toEqual({ modelId: terra.modelRef });
  });

  it("shows the session level while following the session, and the pin while overridden", () => {
    expect(displayedComposerEffort({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "high",
      selection: null,
      model: luna,
    })).toBe("high");
    expect(displayedComposerEffort({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "low",
      selection: { modelId: sol.modelRef, reasoningEffort: "medium" },
      model: sol,
    })).toBe("medium");
  });

  it("repairs a stored pin onto a level the selected model allows", () => {
    expect(normalizeStoredComposerModelSelection({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "high",
      selection: { modelId: sol.modelId },
      choices,
    })).toEqual({ modelId: sol.modelRef, reasoningEffort: "high" });
    expect(normalizeStoredComposerModelSelection({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "low",
      selection: { modelId: luna.modelRef, reasoningEffort: "high" },
      choices,
    })).toBeNull();
    expect(normalizeStoredComposerModelSelection({
      sessionDefaultModelId: luna.modelRef,
      sessionEffort: "low",
      selection: { modelId: "missing/model", reasoningEffort: "high" },
      choices,
    })).toEqual({ modelId: "missing/model", reasoningEffort: "high" });
  });

  it("keeps ordinary chat thinking on the Agent-bound model", () => {
    const workbench = readFileSync(
      new URL("../../routes/chat/ChatCodingRouteWorkbench.tsx", import.meta.url),
      "utf8",
    );
    expect(workbench).toContain("model: agentModel");
    expect(workbench).toContain('currentReasoningEffort: sessionLlmOptions?.currentReasoningEffort ?? ""');
    expect(workbench).toContain("sessionModelParametersMutation.mutate({");
    expect(workbench).toContain("expectedModelRef: options.model.modelRef");
    expect(workbench).not.toContain("selectionAfterModelPick(");
    expect(workbench).not.toContain("if (!followingSessionModel && overrideModel)");
  });

  it("groups models by provider without reordering", () => {
    expect(groupComposerModelChoices(choices).map((group) => ({
      key: group.key,
      labels: group.choices.map((choice) => choice.label),
    }))).toEqual([
      { key: "ai-pixel", labels: ["Luna 5.6", "Sol 4"] },
      { key: "other", labels: ["Terra"] },
    ]);
  });
});
