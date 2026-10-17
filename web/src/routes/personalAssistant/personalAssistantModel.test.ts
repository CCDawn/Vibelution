import { describe, expect, it } from "vitest";
import type { PersonalAssistant } from "../../api/types/personalAssistant";
import {
  PERSONAL_ASSISTANT_RENDERERS,
  personalAssistantAppearance,
  validPersonalAssistant,
} from "./personalAssistantModel";

const assistant: PersonalAssistant = { agentId: "assistant-agent", directSessionId: "assistant-session", displayName: "个人助理",
  status: "active", setupStatus: "ready", profile: "personal_assistant_v1", renderer: "whale" };

describe("personal assistant renderer whitelist", () => {
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
