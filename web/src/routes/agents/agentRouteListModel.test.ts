import { describe, expect, it } from "vitest";

import type { AgentConfigWorkspaceAgent, AgentModelChoice } from "../../api/types";
import {
  agentLabel,
  agentModelChoiceAllowed,
  buildAgentModelChoices,
  normalizeText,
  promptTemplateDisplayName,
} from "./agentRouteListModel";

describe("agentRouteListModel", () => {
  it("normalizes search text and labels agents", () => {
    expect(normalizeText("  Hello ")).toBe("hello");
    const agent = {
      agentId: "a1",
      displayName: "助手",
      agentCode: "A01",
    } as AgentConfigWorkspaceAgent;
    expect(agentLabel(agent)).not.toBe("-");
    expect(agentLabel(null)).toBe("-");
  });

  it("builds selectable model choices and filters image models", () => {
    const models = [
      {
        modelId: "m1",
        label: "gpt",
        model: "gpt",
        providerId: "p",
        providerLabel: "P",
        providerKind: "openai",
        runtimeSelectable: true,
      },
      {
        modelId: "img",
        label: "image2",
        model: "image2",
        providerId: "p",
        providerLabel: "P",
        providerKind: "openai",
        runtimeSelectable: true,
      },
    ] as AgentModelChoice[];
    expect(agentModelChoiceAllowed(models[1])).toBe(false);
    const choices = buildAgentModelChoices(models);
    expect(choices).toHaveLength(1);
    expect(choices[0].modelId).toBe("m1");
  });

  it("maps known prompt template display names in zh", () => {
    expect(promptTemplateDisplayName({ name: "Chat Default" }, "x", "zh")).toBe("会话默认");
    expect(promptTemplateDisplayName({ name: "Chat Default" }, "x", "en")).toBe("Chat Default");
  });
});
