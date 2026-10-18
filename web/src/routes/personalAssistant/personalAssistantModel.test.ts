import { describe, expect, it } from "vitest";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import {
  PERSONAL_ASSISTANT_RENDERERS,
  assistantStatusLabel,
  personalAssistantAppearance,
  validPersonalAssistant,
} from "./personalAssistantModel";

const assistant: PersonalAssistant = { agentId: "assistant-agent", directSessionId: "assistant-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };

describe("personal assistant renderer whitelist", () => {
  it("localizes runtime phases while preserving unrecognized status values", () => {
    expect(assistantStatusLabel("tooling", "en")).toBe("Using tools");
    expect(assistantStatusLabel("waiting_approval", "en")).toBe("Awaiting confirmation");
    expect(assistantStatusLabel("tooling", "zh")).toBe("操作工具中");
    expect(assistantStatusLabel("custom_phase", "en")).toBe("custom_phase");
  });
  it("accepts both appearance renderers and rejects anything else", () => {
    expect(validPersonalAssistant(assistant)).toBe(true);
    expect(validPersonalAssistant({ ...assistant, renderer: "xiaoluo" })).toBe(true);
    expect(validPersonalAssistant({ ...assistant, renderer: "dafeiyu" as PersonalAssistant["renderer"] })).toBe(false);
    expect(validPersonalAssistant({ ...assistant, renderer: "other" as PersonalAssistant["renderer"] })).toBe(false);
    expect(PERSONAL_ASSISTANT_RENDERERS).toEqual(["whale", "xiaoluo"]);
  });
  it("maps renderer back to the dafeiyu/xiaoluo appearance ids", () => {
    expect(personalAssistantAppearance("whale")).toBe("dafeiyu");
    expect(personalAssistantAppearance("xiaoluo")).toBe("xiaoluo");
    expect(personalAssistantAppearance("unknown")).toBe("dafeiyu");
  });
});
