import { describe, expect, it } from "vitest";

import type { TranslationKey } from "../../i18n/dictionaryTypes";
import {
  promotionStatusLabel,
  promotionStatusTone,
  shortPromotionCommit,
} from "./evolutionBaselinePromotion";

describe("evolutionBaselinePromotion", () => {
  it("shortens commits and maps status tone", () => {
    expect(shortPromotionCommit("abcdefghijklmnop")).toBe("abcdefghijkl");
    expect(shortPromotionCommit("")).toBe("--");
    expect(promotionStatusTone("current")).toBe("success");
    expect(promotionStatusTone("superseded")).toBe("warning");
    expect(promotionStatusTone("none")).toBe("neutral");
  });

  it("labels the single git promotion lane", () => {
    const t = (key: TranslationKey) => key;
    expect(
      promotionStatusLabel({ status: "current" } as never, "zh", t),
    ).toBe("promotionCurrent");
    expect(
      promotionStatusLabel({ status: "none" } as never, "en", t),
    ).toBe("promotionNone");
  });
});
