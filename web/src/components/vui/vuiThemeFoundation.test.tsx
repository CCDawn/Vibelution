import React from "react";
import { readFileSync, readdirSync } from "node:fs";
import { resolve } from "node:path";
import { Search } from "lucide-react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VActionGroup,
  VButton,
  VDenseTable,
  VMetricStrip,
  VPage,
  VSection,
  VSurface,
} from "./index";

const designRoot = resolve(import.meta.dirname, "../../design");
const routesRoot = resolve(import.meta.dirname, "../../routes");
const baseSource = readFileSync(resolve(designRoot, "base.css"), "utf8");
const tokensSource = readFileSync(resolve(designRoot, "tokens.css"), "utf8");
const shellStylesSource = readFileSync(resolve(designRoot, "workbench-shell.css"), "utf8");
const tailwindSource = readFileSync(resolve(designRoot, "tailwind.css"), "utf8");
const providerThemeSource = readFileSync(resolve(designRoot, "vui-provider-theme.css"), "utf8");
const routeStyleMapSource = readdirSync(routesRoot)
  .filter((fileName) => fileName.endsWith(".styles.ts"))
  .map((fileName) => readFileSync(resolve(routesRoot, fileName), "utf8"))
  .join("\n");
const agentWorkspacePanelSource = readFileSync(
  resolve(import.meta.dirname, "product/agent-management/AgentWorkspacePanel.tsx"),
  "utf8",
);
const agentSummaryStripSource = readFileSync(
  resolve(import.meta.dirname, "product/agent-management/AgentSummaryStrip.tsx"),
  "utf8",
);

describe("VUI dual-theme foundation", () => {
  it("defines shared semantic tokens for light and dark theme surfaces", () => {
    for (const token of [
      "--vui-surface-glass",
      "--vui-surface-toolbar",
      "--vui-surface-row",
      "--vui-surface-workspace",
      "--vui-surface-region",
      "--vui-surface-card",
      "--vui-surface-inset",
      "--vui-surface-control",
      "--vui-surface-popover",
      "--vui-surface-row-hover",
      "--vui-control-muted",
      "--vui-control-muted-hover",
      "--vui-control-hover-bg",
      "--vui-control-hover-border",
      "--vui-control-hover-fg",
      "--vui-control-hover-shadow",
      "--vui-row-hover-bg",
      "--vui-border-subtle",
      "--vui-status-info-bg",
      "--vui-status-success-bg",
      "--vui-status-warning-bg",
      "--vui-status-danger-bg",
      "--vui-shadow-none",
      "--vui-radius-panel-soft",
      "--vui-radius-overlay",
      "--vui-elevation-panel",
      "--vui-elevation-overlay",
      "--fg-muted",
      "--fg-subtle",
      "--accent-primary",
      "--accent-success",
      "--accent-warning",
      "--accent-danger",
      "--accent-cool-contrast",
      "--state-danger",
      "--surface-base",
      "--surface-elevated",
      "--surface-toolbar",
      "--border-subtle",
      "--font-size-micro",
      "--font-size-caption",
      "--font-size-small",
      "--font-size-body",
      "--font-size-title",
    ]) {
      expect(tokensSource).toContain(token);
    }

    expect(tokensSource).toContain("--vui-radius-panel-soft: 12px;");
    expect(tokensSource).toContain("--vui-radius-overlay: 12px;");
    expect(tokensSource).toContain("--radius-control: 8px;");
    expect(tokensSource).toContain("--radius-panel: var(--vui-radius-panel-soft);");
    expect(tokensSource).toContain("--radius-card: var(--vui-radius-panel-soft);");
    expect(tokensSource).toContain("--vui-elevation-panel: var(--vui-elevation-1-sheen);");
    expect(tokensSource).toContain("--vui-elevation-overlay: var(--vui-elevation-2-sheen);");
    expect(tailwindSource).toContain("--color-vui-surface-rail: var(--vui-surface-rail)");
    expect(tailwindSource).toContain("--color-vui-surface-raised: var(--vui-surface-raised)");
    expect(tailwindSource).toContain("--color-vui-surface-card: var(--vui-surface-card)");
    expect(tailwindSource).toContain("--color-vui-surface-popover: var(--vui-surface-popover)");

    const lightThemeBlock = tokensSource.slice(tokensSource.indexOf('[data-theme="light"]'));
    expect(lightThemeBlock).toContain("--vui-surface-glass");
    expect(lightThemeBlock).toContain("--vui-surface-card");
    expect(lightThemeBlock).toContain("--vui-surface-popover");
    expect(lightThemeBlock).toContain("--vui-control-muted");
    expect(lightThemeBlock).toContain("--vui-control-hover-bg");
    expect(lightThemeBlock).toContain("--vui-control-hover-border");
    expect(lightThemeBlock).toContain("--vui-row-hover-bg");
    expect(lightThemeBlock).toContain("--vui-status-info-bg");
    expect(lightThemeBlock).toContain("--accent-cool-contrast");
    expect(lightThemeBlock).toContain("--surface-elevated");
    expect(tokensSource).toContain("--vui-select-chevron");
    expect(lightThemeBlock).toContain("--vui-select-chevron");
    expect(tokensSource).toContain("--vui-surface-toolbar: var(--vui-surface-raised);");
    expect(tokensSource).toContain("--vui-surface-row: rgb(24 30 40);");
    // VUI owns literals; legacy --surface-* only aliases into VUI (never reverse).
    expect(lightThemeBlock).toContain("--vui-surface-row: #f4f7fb;");
    expect(lightThemeBlock).toContain("--surface-card-muted: var(--vui-surface-row);");
    expect(tokensSource).toContain("--surface-page: var(--vui-surface-workspace);");
    expect(tokensSource).toContain("--surface-panel: var(--vui-surface-panel);");
    expect(tokensSource).toContain("--surface-card: var(--vui-surface-card);");
    expect(tokensSource).not.toContain("--vui-surface-row: var(--surface-card-muted);");
    expect(tokensSource).not.toContain("--vui-surface-row: color-mix(in srgb, var(--surface-card) 86%, transparent);");
  });

  it("keeps structural shell surfaces opaque while reserving glass for explicit overlay roles", () => {
    expect(shellStylesSource).toContain("--shell-surface: var(--vui-surface-rail);");
    expect(shellStylesSource).toContain("--shell-panel: var(--vui-surface-panel);");
    expect(shellStylesSource).toContain("--shell-card: var(--vui-surface-row);");
    expect(shellStylesSource).not.toContain("color-mix(in srgb, var(--shell-panel)");
    expect(shellStylesSource).not.toContain("color-mix(in srgb, var(--shell-card)");
    expect(tokensSource).toContain("--vui-surface-glass: color-mix(in srgb, var(--vui-surface-panel) 88%, transparent);");
  });

  it("keeps shadcn-native form renderers dual-theme safe", () => {
    const selectSource = readFileSync(
      resolve(import.meta.dirname, "renderers/shadcn/ShadcnSelect.tsx"),
      "utf8",
    );
    const formClassesSource = readFileSync(
      resolve(import.meta.dirname, "forms/formClasses.ts"),
      "utf8",
    );
    const nativeControlsSource = readFileSync(
      resolve(designRoot, "vui-native-controls.css"),
      "utf8",
    );

    expect(selectSource).toContain("bg-[image:var(--vui-select-chevron)]");
    expect(selectSource).not.toContain("%237d8796");
    expect(formClassesSource).toContain("[color-scheme:inherit]");
    expect(nativeControlsSource).toContain('select[data-renderer="shadcn"] option');
    expect(nativeControlsSource).toContain("color-scheme: inherit");
    expect(nativeControlsSource).toContain("background-color: var(--vui-surface-input)");
    expect(nativeControlsSource).toContain("color: var(--fg-primary)");
  });

  it("keeps the app readable without relying on browser zoom", () => {
    expect(baseSource).toContain("font-size: 16px");
    expect(baseSource).not.toContain("font-size: 14px");
    expect(baseSource).not.toContain("font-size: 15px");
  });

  it("maps Tailwind and provider theme classes to Vibelution semantic tokens", () => {
    expect(tailwindSource).toContain("@theme inline");
    expect(tailwindSource).toContain("--color-vui-surface-glass: var(--vui-surface-glass)");
    expect(tailwindSource).toContain("--color-vui-surface-toolbar: var(--vui-surface-toolbar)");
    expect(tailwindSource).toContain("--color-vui-surface-row: var(--vui-surface-row)");
    expect(tailwindSource).toContain("--color-vui-surface-page: var(--vui-surface-workspace)");
    expect(tailwindSource).toContain("--color-vui-control-muted: var(--vui-control-muted)");
    expect(tailwindSource).toContain("--color-vui-border-subtle: var(--vui-border-subtle)");
    expect(providerThemeSource).toContain("--vui-component-border");
    expect(providerThemeSource).toContain("--vui-component-surface");
    expect(providerThemeSource).toContain('[data-vui-provider="shadcn"]');
    expect(providerThemeSource).toContain('button[data-vui="button"]');
    expect(providerThemeSource).toContain("border-width: 1px");
    expect(providerThemeSource).toContain("--vui-component-control-hover-bg");
    expect(providerThemeSource).toContain("--vui-component-control-hover-border");
    expect(providerThemeSource).toContain("--vui-component-control-hover-fg");
    expect(providerThemeSource).toContain(".vui-tone-danger");
  });

  it("exports shared opaque surface recipes for route style maps", () => {
    const recipesSource = readFileSync(resolve(designRoot, "vuiSurfaceRecipes.ts"), "utf8");
    expect(recipesSource).toContain("export const vuiOpaquePanelClass");
    expect(recipesSource).toContain("export const vuiFlatPanelClass");
    expect(recipesSource).toContain("export const vuiElevatedPanelClass");
    expect(recipesSource).toContain("export const vuiOpaqueRowClass");
    expect(recipesSource).toContain("export const vuiDenseRowClass");
    expect(recipesSource).toContain("export const vuiGlassPanelClass");
    expect(recipesSource).toContain("!bg-[var(--vui-surface-panel)]");
    expect(recipesSource).toContain("!bg-[var(--vui-surface-row)]");
    expect(recipesSource).toContain("hover:bg-[var(--vui-surface-row-hover)]");
    expect(recipesSource).toContain("shadow-[var(--vui-elevation-1)]");
    expect(recipesSource).toContain("bg-[var(--vui-surface-glass)]");
    expect(recipesSource).not.toContain("var(--surface-");
  });

  it("keeps production CSS consumers on VUI surface tokens instead of legacy aliases", () => {
    const baseSource = readFileSync(resolve(designRoot, "base.css"), "utf8");
    const shellSource = readFileSync(resolve(designRoot, "workbench-shell.css"), "utf8");
    const codeMirrorSource = readFileSync(resolve(designRoot, "codeMirrorTheme.ts"), "utf8");
    expect(baseSource).toContain("var(--vui-surface-workspace)");
    expect(baseSource).toContain("var(--vui-surface-input)");
    expect(baseSource).not.toContain("var(--surface-");
    expect(shellSource).toContain("var(--vui-surface-overlay)");
    expect(shellSource).not.toContain("var(--surface-overlay)");
    expect(codeMirrorSource).toContain("var(--vui-surface-workspace)");
    expect(codeMirrorSource).not.toContain("var(--surface-code)");
    expect(tokensSource).toContain("--vui-surface-input:");
    expect(tokensSource).toContain("--vui-surface-overlay:");
  });

  it("defines the readable display scale as shared tokens instead of page-local micro text", () => {
    for (const token of [
      "--vui-font-xs",
      "--vui-font-sm",
      "--vui-font-md",
      "--vui-font-chat",
      "--vui-line-readable",
      "--vui-control-height-compact",
      "--vui-control-height-comfortable",
    ]) {
      expect(tokensSource).toContain(token);
    }

    expect(tokensSource).toContain("--vui-font-xs: 0.875rem;");
    expect(tokensSource).toContain("--vui-font-sm: 0.9375rem;");
    expect(tokensSource).toContain("--vui-font-md: 1rem;");
    expect(tokensSource).toContain("--vui-font-chat: 1.0625rem;");
    expect(tokensSource).toContain("--vui-font-title: 1.1875rem;");
    expect(baseSource).toContain("font-size: 16px");
    expect(tailwindSource).toContain(":where(small)");
    expect(tailwindSource).toContain(".text-xs");
    expect(tailwindSource).toContain("font-size: var(--vui-font-xs)");

    const vuiSources = [
      agentWorkspacePanelSource,
      agentSummaryStripSource,
      readFileSync(resolve(import.meta.dirname, "layout/VStatusStrip.tsx"), "utf8"),
      readFileSync(resolve(import.meta.dirname, "display/VMetricStrip.tsx"), "utf8"),
      readFileSync(resolve(import.meta.dirname, "display/VDenseTable.tsx"), "utf8"),
      readFileSync(resolve(import.meta.dirname, "layout/VSection.tsx"), "utf8"),
      readFileSync(resolve(import.meta.dirname, "primitives/VChip.tsx"), "utf8"),
      readFileSync(resolve(import.meta.dirname, "primitives/VTooltip.tsx"), "utf8"),
    ].join("\n");

    expect(vuiSources).not.toMatch(/text-\[0\.(?:6\d|7[0-7])rem\]/);
    expect(vuiSources).not.toContain("text-xs");
    // Tailwind treats text-[var(--vui-font-*)] as color; use explicit font-size.
    expect(vuiSources).toContain("[font-size:var(--vui-font-xs)]");
    expect(vuiSources).not.toMatch(/(?<!font-size:)(?<!length:)text-\[var\(--vui-font-xs\)\]/);
  });

  it("keeps migrated route style maps free of page-local sub-14px typography", () => {
    const subReadableFontPattern =
      /(?:font-size:\s*|text-\[)0\.[5-8]\d*rem\]?/g;

    expect(routeStyleMapSource.match(subReadableFontPattern) ?? []).toEqual([]);
    expect(routeStyleMapSource).not.toContain(".module.css");
    expect(routeStyleMapSource).not.toContain(".vui.css");
  });

  it("renders page, surface, section, metric strip, and action group primitives", () => {
    const markup = renderToStaticMarkup(
      <VPage ariaLabel="Agent workspace">
        <VSurface aria-label="Surface" tone="glass">
          <VSection
            title="Agents"
            meta={<span>32</span>}
            actions={
              <VActionGroup ariaLabel="Agent actions">
                <VButton icon={<Search size={14} />}>搜索</VButton>
              </VActionGroup>
            }
          >
            <VMetricStrip
              ariaLabel="Agent metrics"
              metrics={[
                { label: "可用", value: "32", tone: "success" },
                { label: "运行中", value: "0", tone: "info" },
              ]}
            />
            <VDenseTable
              ariaLabel="Agent table"
              columns={[
                { id: "name", header: "Agent", render: (row) => row.name },
                { id: "role", header: "职责", render: (row) => row.role },
              ]}
              rows={[{ id: "a001", name: "唐南栀", role: "知识管理员" }]}
              getRowKey={(row) => row.id}
            />
          </VSection>
        </VSurface>
      </VPage>,
    );

    expect(markup).toContain('data-vui="page"');
    expect(markup).toContain('data-vui="surface"');
    expect(markup).toContain('data-vui="section"');
    expect(markup).toContain('data-vui="metric-strip"');
    expect(markup).toContain('data-vui="dense-table"');
    expect(markup).toContain('data-vui="action-group"');
    expect(markup).toContain("可用");
    expect(markup).toContain("运行中");
  });

  it("moves Agent Management product panels onto shared VUI primitives", () => {
    expect(agentWorkspacePanelSource).toContain("VSurface");
    expect(agentWorkspacePanelSource).toContain('data-vui-product="agent-workspace-panel"');
    expect(agentSummaryStripSource).toContain("VMetricStrip");
    expect(agentSummaryStripSource).toContain('data-vui-product="agent-summary-strip"');
  });
});
