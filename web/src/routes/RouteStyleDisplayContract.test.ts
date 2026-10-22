import { readdirSync, readFileSync } from "node:fs";
import { basename } from "node:path";

import { describe, expect, it } from "vitest";

import chatRouteSource from "./chat/ChatCodingRouteWorkbench.tsx?raw";
import chatLayoutSource from "./chat/useChatWorkbenchLayout.ts?raw";
import directSessionIndexItemSource from "./DirectSessionIndexItem.tsx?raw";
import gitRouteSource from "./GitRoute.tsx?raw";
import selfEvolutionTrackSource from "./SelfEvolutionTrack.tsx?raw";
import agentWorkspaceSource from "./AgentWorkspaceLayoutPanel.tsx?raw";
import agentWorkspaceStyles from "./AgentWorkspaceLayoutPanel.styles";

type StyleEntry = {
  file: string;
  key: string;
  value: string;
};

const routeDir = new URL(".", import.meta.url);
const styleEntryPattern = /^\s*([A-Za-z0-9_]+):\s*\r?\n?\s*"([^"]*)"/gm;
const hostGridDisplayClasses = new Set(["grid", "!grid", "inline-grid", "!inline-grid"]);
const hostGridTemplatePattern = /^!?(grid-cols|grid-rows|grid-flow|auto-rows|auto-cols)-/;
const composedGridTemplateModifiers = new Set([
  "ChatCodingRoute.styles.ts:layoutCompactDesktop",
  "ChatCodingRoute.styles.ts:rightPaneWithTabs",
  "ChatCodingRoute.styles.ts:rightPaneWithoutTabs",
  "ChatCodingRoute.styles.ts:sessionRowHost",
  "ChatCodingRoute.styles.ts:centerPaneBodyRow",
  "ConfigRoute.styles.ts:configAdvancedGrid",
  "ConfigRoute.styles.ts:treeFieldCardView",
  "GitRoute.styles.ts:workspaceOverview",
  "GitRoute.styles.ts:historyPanel",
  "GitRoute.styles.ts:modelActionRow",
  "GitRoute.styles.ts:pendingChangePanel",
  "DirectSessionIndexItem.styles.ts:sessionItemWithBulkSelect",
  "AgentWorkspaceLayoutPanel.styles.ts:directoryWithActions",
]);

function readRouteStyleEntries(): StyleEntry[] {
  return readdirSync(routeDir, { withFileTypes: true })
    .filter((entry) => entry.isFile() && entry.name.endsWith(".styles.ts"))
    .flatMap((entry) => {
      const source = readFileSync(new URL(entry.name, routeDir), "utf-8");
      return Array.from(source.matchAll(styleEntryPattern), (match) => ({
        file: basename(entry.name),
        key: match[1],
        value: match[2],
      }));
    });
}

function utilityTail(token: string) {
  const segments = token.split(":");
  return segments[segments.length - 1] ?? token;
}

function hostUtilityTokens(className: string) {
  return className
    .split(/\s+/)
    .filter(Boolean)
    .filter((token) => !token.includes("[&"));
}

function hasHostGridDisplay(className: string) {
  return hostUtilityTokens(className).some((token) => hostGridDisplayClasses.has(utilityTail(token)));
}

function hasHostGridTemplate(className: string) {
  return hostUtilityTokens(className).some((token) => hostGridTemplatePattern.test(utilityTail(token)));
}

describe("route style display contract", () => {
  it("keeps route host grid template utilities paired with a host grid display utility", () => {
    const violations = readRouteStyleEntries()
      .filter((entry) => hasHostGridTemplate(entry.value) && !hasHostGridDisplay(entry.value))
      .map((entry) => `${entry.file}:${entry.key}`)
      .filter((id) => !composedGridTemplateModifiers.has(id));

    expect(violations).toEqual([]);
  });

  it("keeps composed grid-template modifiers attached to grid-bearing base styles", () => {
    expect(chatLayoutSource).toContain("`${styles.layout} ${styles.layoutCompactDesktop}`");
    expect(chatLayoutSource).toContain("`${styles.rightPane} ${rightPaneLayoutClassName}`");
    expect(chatRouteSource).toContain("className={chatLayoutClassName}");
    expect(chatLayoutSource).toContain("sessionRowSpansRail ? styles.sessionRowHost");
    expect(chatLayoutSource).toContain('`${styles.centerPane} ${styles.centerPaneDocked}`}${sessionRowSpansRail ? ` ${styles.centerPaneBodyRow}`');
    const chatStyles = readFileSync(new URL("./ChatCodingRoute.styles.ts", import.meta.url), "utf8");
    for (const key of ["layout", "centerPane"]) {
      const baseClasses = chatStyles.match(new RegExp(`${key}:\\s*` + "`([^`]*)`"))?.[1] ?? "";
      expect(hasHostGridDisplay(baseClasses), `${key} must own the grid display`).toBe(true);
    }

    expect(gitRouteSource).toContain("`${styles.workspace} ${styles.workspaceOverview}`");
    expect(gitRouteSource).toContain("cn(styles.commitPanel, styles.historyPanel, VUI_WORKBENCH_PANE_CLASS)");
    expect(gitRouteSource).toContain("`${styles.modelDefaultRow} ${styles.modelActionRow}`");
    expect(gitRouteSource).toContain("cn(styles.changePanel, styles.pendingChangePanel,");
    const gitStyles = readFileSync(new URL("./GitRoute.styles.ts", import.meta.url), "utf8");
    const changePanelClasses = gitStyles.match(/changePanel:\s*"([^"]*)"/)?.[1] ?? "";
    expect(hasHostGridDisplay(changePanelClasses)).toBe(true);

    // Settings-align wave 3: ConfigSectionEditor (the only consumer of these
    // composed classes) moved to config/ConfigSectionEditor.tsx; the contract
    // follows the code (assertion text unchanged).
    const configSectionEditorSource = readFileSync(new URL("./config/ConfigSectionEditor.tsx", import.meta.url), "utf-8");
    expect(configSectionEditorSource).toContain("`${styles.treeGrid} ${styles.configAdvancedGrid}`");
    // Settings-align wave 1: plain fields render as VSettingsRow; the composed
    // grid-template card styles remain attached to the image cards. Wave 2's
    // layout unification made the background card full-width single-column
    // (no treeFieldHead/treeFieldValue pair), so it drops treeFieldCardView.
    expect(configSectionEditorSource).toContain("`${styles.treeFieldCard} ${styles.themeBackgroundImageCard}`");
    expect(configSectionEditorSource).toContain("`${styles.treeFieldCard} ${styles.treeFieldCardView} ${styles.avatarImageCard}`");

    expect(directSessionIndexItemSource).toContain("styles.sessionItem,");
    expect(directSessionIndexItemSource).toContain("bulkSelectionEnabled ? styles.sessionItemWithBulkSelect");

    expect(selfEvolutionTrackSource).toContain("className={styles.centerColumn}");
    expect(agentWorkspaceStyles.directory).toMatch(/\bgrid\b/);
    expect(agentWorkspaceSource).toContain('className={[styles.directory, directoryActions ? styles.directoryWithActions : ""].filter(Boolean).join(" ")}');
  });
});
