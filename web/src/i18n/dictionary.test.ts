import { describe, expect, it } from "vitest";

import { dictionary } from "./dictionary";
import { petAvatarPresetLabel } from "./petLabels";
import { shellDictionary } from "./shellDictionary";

describe("dictionary", () => {
  it("keeps the pet area readable in Chinese", () => {
    const keys = [
      "petSpace",
      "vitals",
      "mood",
      "hunger",
      "energy",
      "health",
      "love",
      "progress",
      "state",
      "heart",
      "dream",
      "dailyTokens",
      "achievements",
      "petAchievementFirstTask",
      "petAchievementLevel10",
      "petPresetLobster",
      "petPresetShrimp",
      "petPresetCrab",
      "petPresetCat",
      "petPresetChick",
      "petPresetBunny",
      "petPresetSlime",
      "petPresetPenguin",
      "petPresetMoose",
      "petPresetUnknown",
    ] as const;

    for (const key of keys) {
      const value = dictionary.zh[key];

      expect(value).toBeTruthy();
      expect(value).not.toMatch(/[A-Za-z]/);
    }
  });

  it("maps pet avatar preset ids to user-facing labels", () => {
    const t = (key: keyof typeof dictionary.zh) => dictionary.zh[key];

    expect(petAvatarPresetLabel(t, "lobster")).toBe("龙虾宝宝");
    expect(petAvatarPresetLabel(t, "penguin")).toBe("企鹅");
    expect(petAvatarPresetLabel(t, "")).toBe("未选择形象");
    expect(petAvatarPresetLabel(t, "custom_preset")).toBe("custom_preset");
  });

  it("keeps the lightweight shell dictionary aligned with the full route dictionary", () => {
    const shellKeys = Object.keys(shellDictionary.zh) as Array<keyof typeof shellDictionary.zh>;

    for (const key of shellKeys) {
      const routeKey = key as keyof typeof dictionary.zh;

      expect(shellDictionary.zh[key]).toBe(dictionary.zh[routeKey]);
      expect(shellDictionary.en[key]).toBe(dictionary.en[routeKey]);
    }
  });
});
