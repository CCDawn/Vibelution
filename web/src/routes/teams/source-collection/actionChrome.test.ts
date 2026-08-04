import { describe, expect, it } from "vitest";

import {
  SOURCE_COLLECTION_ACTION_READY,
  sourceCollectionActionDisabledTitle,
  sourceCollectionActionReadinessOf,
  sourceCollectionLoadingChrome,
} from "./actionChrome";

describe("source-collection actionChrome", () => {
  it("builds bilingual loading chrome", () => {
    expect(sourceCollectionLoadingChrome("zh").loadingText).toBe("加载中");
    expect(sourceCollectionLoadingChrome("en").loadingText).toBe("loading");
  });

  it("builds readiness and disabled titles", () => {
    expect(sourceCollectionActionReadinessOf(false, "x")).toEqual(SOURCE_COLLECTION_ACTION_READY);
    const blocked = sourceCollectionActionReadinessOf(true, "busy", true);
    expect(blocked).toEqual({ disabled: true, loading: true, reason: "busy" });
    expect(sourceCollectionActionDisabledTitle(blocked, "fallback")).toBe("busy");
    expect(sourceCollectionActionDisabledTitle(SOURCE_COLLECTION_ACTION_READY, "fallback")).toBe("fallback");
  });
});
