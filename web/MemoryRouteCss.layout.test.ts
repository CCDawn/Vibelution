import { describe, expect, it } from "vitest";

import knowledgeBaseSidebarStyles from "./src/routes/MemoryKnowledgeBaseSidebar.styles";
import itemListStyles from "./src/routes/MemoryItemListPanel.styles";

describe("MemoryRoute CSS layout contract", () => {
  it("clips long memory list text so raw HTML summaries cannot overlap cards", () => {
    expect(itemListStyles.itemButton).toBeTypeOf("string");
    expect(itemListStyles.itemContentButton).toBeTypeOf("string");
    expect(knowledgeBaseSidebarStyles.sourceCopy).toBeTypeOf("string");
    expect(itemListStyles.itemPath).toBeTypeOf("string");
    expect(itemListStyles.itemSummary).toBeTypeOf("string");
    expect(itemListStyles.itemButtonDense).toContain("min-h-[62px]");
    expect(itemListStyles.itemContentButtonDense).toContain("grid-rows-[16px_14px_18px]");
  });
});
