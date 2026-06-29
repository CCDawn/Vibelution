import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(import.meta.dirname, "../..");

const migrationTargets = [
  {
    path: "app/AppShellUtilityMenu.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "components/layout/PaneCollapseHandle.tsx",
    expectedPrimitive: "VIconButton",
  },
  {
    path: "components/preview/FilePreview.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "components/preview/StructuredLogPreview.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "routes/SkillsRoute.tsx",
    expectedPrimitive: "VButton",
  },
  {
    path: "routes/PromptTemplatesRoute.tsx",
    expectedPrimitive: "VButton",
  },
] as const;

const slottedListStyleTargets = [
  {
    path: "app/AppShell.module.css",
    outerSelector: ".utilityFileButton",
    contentSlot: '.utilityFileButton [data-slot="vui-button-content"]',
    labelSlot: '.utilityFileButton [data-slot="vui-button-label"]',
  },
  {
    path: "routes/SkillsRoute.module.css",
    outerSelector: ".skillButton,\n.skillButtonActive",
    contentSlot: '.skillButton [data-slot="vui-button-content"]',
    labelSlot: '.skillButton [data-slot="vui-button-label"]',
  },
  {
    path: "routes/PromptTemplatesRoute.module.css",
    outerSelector: ".templateButton,\n.templateButtonActive",
    contentSlot: '.templateButton [data-slot="vui-button-content"]',
    labelSlot: '.templateButton [data-slot="vui-button-label"]',
  },
] as const;

function readTargetSource(path: string): string {
  return readFileSync(resolve(sourceRoot, path), "utf8");
}

function readStyleBlock(source: string, selector: string): string {
  const start = source.indexOf(selector);
  expect(start).toBeGreaterThanOrEqual(0);
  const end = source.indexOf("}", start);
  expect(end).toBeGreaterThan(start);
  return source.slice(start, end + 1);
}

describe("VUI batch migration", () => {
  it.each(migrationTargets)(
    "$path uses VUI controls instead of raw buttons",
    ({ path, expectedPrimitive }) => {
      const source = readTargetSource(path);

      expect(source).toContain(expectedPrimitive);
      expect(source).not.toContain("<button");
    },
  );

  it.each(slottedListStyleTargets)(
    "$path keeps VUI list button grid on internal slots",
    ({ path, outerSelector, contentSlot, labelSlot }) => {
      const source = readTargetSource(path);
      const outerBlock = readStyleBlock(source, outerSelector);

      expect(outerBlock).toContain("display: block;");
      expect(source).toContain(contentSlot);
      expect(source).toContain(labelSlot);
    },
  );
});
