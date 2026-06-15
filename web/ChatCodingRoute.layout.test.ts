import { readFileSync } from "node:fs";
import { describe, expect, it } from "vitest";

const chatCss = readFileSync(new URL("./src/routes/ChatCodingRoute.module.css", import.meta.url), "utf-8");
const chatRoute = readFileSync(new URL("./src/routes/ChatCodingRoute.tsx", import.meta.url), "utf-8");

function cssRule(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  return chatCss.match(new RegExp(`${escaped}\\s*\\{[^}]*\\}`, "s"))?.[0] ?? "";
}

describe("ChatCodingRoute layout contract", () => {
  it("lets the conversation view fill the center frame so the composer stays at the bottom", () => {
    const frame = cssRule(".conversationFrame");

    expect(frame).toContain("display: flex");
    expect(frame).toContain("flex-direction: column");
    expect(frame).toContain("height: 100%");
    expect(frame).not.toContain("grid-template-rows: auto minmax(0, 1fr)");
  });

  it("keeps the next-turn mental model toggle in the left feature card", () => {
    expect(chatRoute).toContain("styles.featureChipPrimary");
    expect(chatRoute).toContain("onClick={() => handleMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}");
    expect(chatRoute).toContain("title={t(\"chatFeatureMentalModelHint\")}");
    expect(chatRoute.indexOf("styles.featureChipPrimary")).toBeLessThan(chatRoute.indexOf("CHAT_FEATURE_PRESETS.map"));
    expect(chatRoute).not.toContain("mentalModelEnabled={mentalModelEnabledForNextTurn}");
    expect(chatRoute).not.toContain("onMentalModelEnabledChange={handleMentalModelEnabledChange}");
  });
});
