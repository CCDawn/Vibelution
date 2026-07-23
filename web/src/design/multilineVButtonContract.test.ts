import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";

const src = (rel: string) => readFileSync(resolve(import.meta.dirname, "..", rel), "utf8");

describe("multiline VButton hardening (Path B wave 10)", () => {
  it("keeps plain layout free of density height clamps", () => {
    const button = src("components/vui/primitives/VButton.tsx");
    expect(button).toContain('contentLayout === "plain" ? "!h-auto"');
  });

  it("uses plain layout for chat feature chips, pet actions, and model picker cards", () => {
    const chat = src("routes/chat/ChatStatusRail.tsx");
    const picker = src("routes/AgentModelPicker.tsx");
    const token = src("routes/chat/TokenCoreStatusPanel.tsx");
    expect(chat).toMatch(/contentLayout="plain"[\s\S]{0,120}styles\.featureChip/);
    expect(chat).toMatch(/contentLayout="plain"[\s\S]{0,80}styles\.petShowcaseAction/);
    expect(picker).toMatch(/contentLayout="plain"[\s\S]{0,120}styles\.option/);
    expect(token).toMatch(/contentLayout="plain"[\s\S]{0,160}styles\.tokenStatusMetricButton/);
  });

  it("uses natural-height plain layout for Agent management directory rows", () => {
    const skills = src("routes/SkillsRoute.tsx");
    const skillStyles = src("routes/SkillsRoute.styles.ts");
    const prompts = src("routes/PromptTemplatesRoute.tsx");
    const promptStyles = src("routes/PromptTemplatesRoute.styles.ts");
    const tools = src("routes/ToolsRoute.tsx");
    const toolStyles = src("routes/ToolsRoute.styles.ts");

    expect(skills).toMatch(/contentLayout="plain"[\s\S]{0,180}styles\.skillButtonBaseClass/);
    expect(skillStyles).toContain("!h-auto");
    expect(prompts).toMatch(/contentLayout="plain"[\s\S]{0,180}styles\.templateButtonBaseClass/);
    expect(promptStyles).toContain("!h-auto");
    expect(tools).toMatch(/contentLayout="plain"[\s\S]{0,120}styles\.toolButton/);
    expect(toolStyles).toContain("!h-auto");
  });

  it("does not force nowrap on native buttons with explicit grid display", () => {
    const native = src("components/vui/primitives/VNativeButton.tsx");
    expect(native).toContain("displayExplicit ? null : \"whitespace-nowrap\"");
  });
});
