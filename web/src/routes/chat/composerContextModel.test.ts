import { describe, expect, it } from "vitest";
import {
  buildComposerContextRingModel,
  resolveComposerCacheState,
} from "./composerContextModel";
const base = {
  usageUsed: 85865,
  usageLimit: 1000000,
  hitPercent: 99.9,
  detailAvailable: true,
  lang: "zh" as const,
  segments: [
    { key: "history", label: "历史", tokens: 82000, status: "computed_hit" },
    { key: "agent_prompt_snapshot", label: "提示", tokens: 3400 },
    { key: "agent_runtime", label: "规范", tokens: 388 },
    { key: "agent_messages", label: "消息", tokens: 34 },
    { key: "dynamic_runtime_context", label: "运行信息", tokens: 34 },
    { key: "current_user", label: "输入", tokens: 9 },
  ],
};
describe("composerContextModel", () => {
  it("does not present computed candidates as observed hits and groups by source", () => {
    const model = buildComposerContextRingModel(base);
    expect(model.cacheState).toBe("missing");
    expect(model.hitPercent).toBe(0);
    expect(model.groups.map((group) => [group.key, group.tokensLabel])).toEqual(
      [
        ["history", "82K"],
        ["prompt", "3.8K"],
        ["other", "77"],
      ],
    );
    expect(model.groups.flatMap((group) => group.segments)).toHaveLength(6);
    expect(model.usagePercent).toBeCloseTo(8.5865);
    expect(model.usageLabel).toBe("9%");
    expect(model.segments.at(-1)?.pctLabel).toBe("<0.1%");
  });
  it("uses provider observations including measured zero", () => {
    expect(
      buildComposerContextRingModel({
        ...base,
        cacheSource: "provider_usage",
        cacheUsageObserved: true,
        hitPercent: 0,
      }).cacheState,
    ).toBe("observed");
    expect(
      buildComposerContextRingModel({
        ...base,
        cacheSource: "provider_usage",
        cacheUsageObserved: true,
        hitPercent: 76,
      }).hitPercent,
    ).toBe(76);
    expect(
      resolveComposerCacheState({
        cacheSource: "provider_usage",
        cacheUsageObserved: false,
        cachedInputTokens: 50,
      }),
    ).toBe("missing");
    expect(resolveComposerCacheState({ cacheSource: "not_called" })).toBe(
      "not_called",
    );
  });
  it("distinguishes unknown capacity, valid zero, and tiny nonzero usage", () => {
    expect(
      buildComposerContextRingModel({ ...base, usageLimit: 0 }).usageLabel,
    ).toBe("—");
    const zero = buildComposerContextRingModel({
      ...base,
      usageUsed: 0,
      segments: [],
    });
    expect(zero.empty).toBe(false);
    expect(zero.usageLabel).toBe("0%");
    expect(
      buildComposerContextRingModel({ ...base, usageUsed: 9 }).usageLabel,
    ).toBe("<1%");
    expect(
      buildComposerContextRingModel({
        ...base,
        usageUsed: 0,
        usageLimit: 0,
        segments: [],
      }).empty,
    ).toBe(true);
  });
  it("retains new source details and excludes placeholder estimates", () => {
    const model = buildComposerContextRingModel({
      ...base,
      lang: "en",
      segments: [
        {
          key: "new_source",
          label: "New source",
          tokens: 20,
          contentPreview: "Example",
        },
        { key: "computed_missing", label: "Missing", tokens: 1 },
      ],
    });
    expect(model.groups[0].name).toBe("Other content");
    expect(model.segments[0].contentPreview).toBe("Example");
    expect(model.segments).toHaveLength(1);
  });
});
