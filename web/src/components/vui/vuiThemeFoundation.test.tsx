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
const tailwindSource = readFileSync(resolve(designRoot, "tailwind.css"), "utf8");
const herouiThemeSource = readFileSync(resolve(designRoot, "heroui-theme.css"), "utf8");
const routeLegacySource = readFileSync(resolve(designRoot, "vui-route-legacy.css"), "utf8");
const routeModuleLegacySource = readdirSync(routesRoot)
  .filter((fileName) => fileName.endsWith(".legacy.css"))
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
      "--vui-surface-row-hover",
      "--vui-control-muted",
      "--vui-control-muted-hover",
      "--vui-border-subtle",
      "--vui-status-info-bg",
      "--vui-status-success-bg",
      "--vui-status-warning-bg",
      "--vui-status-danger-bg",
      "--vui-shadow-none",
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

    const lightThemeBlock = tokensSource.slice(tokensSource.indexOf('[data-theme="light"]'));
    expect(lightThemeBlock).toContain("--vui-surface-glass");
    expect(lightThemeBlock).toContain("--vui-control-muted");
    expect(lightThemeBlock).toContain("--vui-status-info-bg");
    expect(lightThemeBlock).toContain("--accent-cool-contrast");
    expect(lightThemeBlock).toContain("--surface-elevated");
  });

  it("keeps the app readable without relying on browser zoom", () => {
    expect(baseSource).toContain("font-size: 16px");
    expect(baseSource).not.toContain("font-size: 14px");
    expect(baseSource).not.toContain("font-size: 15px");
  });

  it("maps Tailwind and HeroUI bridge classes to Vibelution semantic tokens", () => {
    expect(tailwindSource).toContain("@theme inline");
    expect(tailwindSource).toContain("--color-vui-surface-glass: var(--vui-surface-glass)");
    expect(tailwindSource).toContain("--color-vui-surface-toolbar: var(--vui-surface-toolbar)");
    expect(tailwindSource).toContain("--color-vui-surface-row: var(--vui-surface-row)");
    expect(tailwindSource).toContain("--color-vui-control-muted: var(--vui-control-muted)");
    expect(tailwindSource).toContain("--color-vui-border-subtle: var(--vui-border-subtle)");
    expect(herouiThemeSource).toContain("--vui-component-border");
    expect(herouiThemeSource).toContain("--vui-component-surface");
    expect(herouiThemeSource).toContain('button[data-slot="button"][data-vui="button"]');
    expect(herouiThemeSource).toContain("border-width: 1px");
    expect(herouiThemeSource).toContain('[class*="segmentedControl"]');
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
    expect(vuiSources).toContain("text-[var(--vui-font-xs)]");
  });

  it("keeps migrated route legacy styles free of sub-14px typography", () => {
    const subReadableFontPattern =
      /(?:font-size:\s*|text-\[)0\.[5-8]\d*rem\]?/g;

    expect(routeLegacySource.match(subReadableFontPattern) ?? []).toEqual([]);
    expect(routeModuleLegacySource.match(subReadableFontPattern) ?? []).toEqual([]);
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
