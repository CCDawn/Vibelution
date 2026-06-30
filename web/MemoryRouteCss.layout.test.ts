import { describe, expect, it } from "vitest";

import routeStyles from "./src/routes/MemoryRoute.styles";

describe("MemoryRoute CSS layout contract", () => {
  it("clips long memory list text so raw HTML summaries cannot overlap cards", () => {
    expect(routeStyles.itemButton).toBeTypeOf("string");
    expect(routeStyles.itemContentButton).toBeTypeOf("string");
    expect(routeStyles.sourceCopy).toBeTypeOf("string");
    expect(routeStyles.itemPath).toBeTypeOf("string");
    expect(routeStyles.itemSummary).toBeTypeOf("string");
    expect(routeStyles.itemButtonDense).toContain("min-h-[62px]");
    expect(routeStyles.itemContentButtonDense).toContain("grid-rows-[16px_14px_18px]");
  });
});
