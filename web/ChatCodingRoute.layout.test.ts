import { describe, expect, it } from "vitest";

import chatStyles from "./src/routes/ChatCodingRoute.styles";
import chatRoute from "./src/routes/ChatCodingRoute.tsx?raw";
import chatSessionWorkspacePanelStyles from "./src/routes/chat/ChatSessionWorkspacePanel.styles";
import chatSessionWorkspacePanelSource from "./src/routes/chat/ChatSessionWorkspacePanel.tsx?raw";
import chatStatusRailSource from "./src/routes/chat/ChatStatusRail.tsx?raw";

describe("ChatCodingRoute layout contract", () => {
  it("lets the conversation view fill the center frame so the composer stays at the bottom", () => {
    expect(chatRoute).toContain("<ChatSessionWorkspacePanel");
    expect(chatSessionWorkspacePanelSource).toContain("styles.conversationFrame");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).toContain("min-w-0");
    expect(chatSessionWorkspacePanelStyles.conversationFrame).not.toContain("grid-rows-[auto_minmax(0,1fr)]");
  });

  it("keeps the next-turn mental model toggle in the left feature card", () => {
    expect(chatStatusRailSource).toContain("styles.featureChipPrimary");
    expect(chatStatusRailSource).toContain(
      "onClick={() => onMentalModelEnabledChange(!mentalModelEnabledForNextTurn)}",
    );
    expect(chatStatusRailSource).toContain("title={t(\"chatFeatureMentalModelHint\")}");
    expect(chatStatusRailSource.indexOf("styles.featureChipPrimary")).toBeLessThan(
      chatStatusRailSource.indexOf("CHAT_FEATURE_PRESETS.map"),
    );
    expect(chatRoute).toContain("mentalModelEnabledForNextTurn={mentalModelEnabledForNextTurn}");
    expect(chatRoute).toContain("onMentalModelEnabledChange={handleMentalModelEnabledChange}");
  });

  it("keeps the current session card in the dense status layout", () => {
    expect(chatStatusRailSource).toContain("styles.currentSessionBlock");
    expect(chatStatusRailSource).toContain("styles.currentSessionLine");
    expect(chatStatusRailSource).toContain("styles.currentSessionMetaList");
    expect(chatStyles.currentSessionBlock).toContain("min-w-0");
    expect(chatStyles.currentSessionMetaList).toContain("min-w-0");
    expect(chatStyles.inlineMetaPill).toContain("[&_strong]:whitespace-normal");
    expect(chatStyles.inlineMetaPill).toContain("[overflow-wrap:anywhere]");
    expect(chatStatusRailSource).not.toContain('label: t("currentTask"),\n        value: currentTaskSummary');
  });
});
