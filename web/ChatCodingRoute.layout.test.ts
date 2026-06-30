import { describe, expect, it } from "vitest";

import chatStyles from "./src/routes/ChatCodingRoute.styles";
import chatRoute from "./src/routes/ChatCodingRoute.tsx?raw";

describe("ChatCodingRoute layout contract", () => {
  it("lets the conversation view fill the center frame so the composer stays at the bottom", () => {
    expect(chatRoute).toContain("styles.conversationFrame");
    expect(chatStyles.conversationFrame).toContain("min-w-0");
    expect(chatStyles.conversationFrame).not.toContain("grid-rows-[auto_minmax(0,1fr)]");
  });

  it("keeps the next-turn mental model toggle in the left feature card", () => {
    expect(chatRoute).toContain("styles.featureChipPrimary");
    expect(chatRoute).toContain("onClick={() => handleMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}");
    expect(chatRoute).toContain("title={t(\"chatFeatureMentalModelHint\")}");
    expect(chatRoute.indexOf("styles.featureChipPrimary")).toBeLessThan(chatRoute.indexOf("CHAT_FEATURE_PRESETS.map"));
    expect(chatRoute).not.toContain("mentalModelEnabled={mentalModelEnabledForNextTurn}");
    expect(chatRoute).not.toContain("onMentalModelEnabledChange={handleMentalModelEnabledChange}");
  });

  it("keeps the current session card in the dense status layout", () => {
    expect(chatRoute).toContain("styles.currentSessionBlock");
    expect(chatRoute).toContain("styles.currentSessionLine");
    expect(chatRoute).toContain("styles.currentSessionMetaList");
    expect(chatStyles.currentSessionBlock).toContain("min-w-0");
    expect(chatStyles.currentSessionMetaList).toContain("min-w-0");
    expect(chatStyles.inlineMetaPill).toContain("[&_strong]:truncate");
    expect(chatStyles.inlineMetaPill).toContain("[&_strong]:whitespace-nowrap");
    expect(chatRoute).not.toContain('label: t("currentTask"),\n        value: currentTaskSummary');
  });
});
