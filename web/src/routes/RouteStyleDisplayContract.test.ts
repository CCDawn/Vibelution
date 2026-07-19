import { readdirSync, readFileSync } from "node:fs";
import { basename } from "node:path";

import { describe, expect, it } from "vitest";

import chatRouteSource from "./ChatCodingRoute.tsx?raw";
import chatLayoutSource from "./chat/useChatWorkbenchLayout.ts?raw";
import gitRouteSource from "./GitRoute.tsx?raw";
import selfEvolutionTrackSource from "./SelfEvolutionTrack.tsx?raw";

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
  "GitRoute.styles.ts:workspaceOverview",
  "GitRoute.styles.ts:historyPanel",
  "GitRoute.styles.ts:modelActionRow",
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

    expect(gitRouteSource).toContain("`${styles.workspace} ${styles.workspaceOverview}`");
    expect(gitRouteSource).toContain("`${styles.commitPanel} ${styles.historyPanel}`");
    expect(gitRouteSource).toContain("`${styles.modelDefaultRow} ${styles.modelActionRow}`");

    expect(selfEvolutionTrackSource).toContain("className={styles.centerColumn}");
  });
});
