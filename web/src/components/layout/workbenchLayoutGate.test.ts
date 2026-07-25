import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

const webSrc = resolve(import.meta.dirname, "../..");
const routesDir = resolve(webSrc, "routes");

/** Allowed legacy single-key names (migration only — do not add new ones). */
const ALLOWED_LEGACY_WIDTH_KEYS = new Set([
  "vibelution.logs.sidebar-width",
  "vibelution.logs.right-rail-width",
  "vibelution.logs.runtime-scenes-sidebar-width",
  "vibelution.tools.left-panel-width",
  "vibelution.git.change-panel-width",
  "vibelution.supervised-review.queue-width",
  "vibelution.evolution.runs-queue-width",
  "vibelution.evolution.library-list-width",
  "vibelution.evolution.live-launch-width",
  "vibelution.evolution.live-run-width",
  "vibelution.evolution.live-io-height",
  "vibelution.self.sidebar.width",
  "vibelution.agent-workspace.column-widths.v1",
]);

const LEGACY_KEY_RE = /["'](vibelution\.[a-z0-9._-]*(?:width|height)[a-z0-9._-]*)["']/gi;

function walkTsFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      walkTsFiles(full, out);
      continue;
    }
    if (/\.(tsx|ts)$/.test(name) && !name.endsWith(".test.ts") && !name.endsWith(".test.tsx")) {
      out.push(full);
    }
  }
  return out;
}

describe("workbench layout gate (Wave 5)", () => {
  it("forbids new ad-hoc width/height localStorage keys outside the migration allowlist", () => {
    const files = walkTsFiles(routesDir);
    const offenders: string[] = [];

    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const match of text.matchAll(LEGACY_KEY_RE)) {
        const key = match[1];
        if (key === "vibelution.pane-layouts.v1" || key === "vibelution.pane-heights.v1") {
          continue;
        }
        if (ALLOWED_LEGACY_WIDTH_KEYS.has(key)) {
          continue;
        }
        // Shared shell store key is not a pane width key.
        if (key === "vibelution-shell-store") {
          continue;
        }
        offenders.push(`${relative(webSrc, file)}: ${key}`);
      }
    }

    expect(offenders, `New legacy keys found:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("keeps Chat workbench on shared axis resize session + registry layout id", () => {
    const chatLayout = readFileSync(resolve(webSrc, "routes/chat/useChatWorkbenchLayout.ts"), "utf-8");
    const chatRoute = readFileSync(resolve(webSrc, "routes/ChatCodingRoute.tsx"), "utf-8");
    expect(chatLayout).toContain("attachAxisResizeSession");
    expect(chatLayout).toContain("CHAT_WORKBENCH_LAYOUT_ID");
    expect(chatLayout).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chatRoute).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chatRoute).toContain("data-vui-layout-id");
  });

  it("keeps Evolution CASE IO on shared height resize handle", () => {
    const evolution = readFileSync(resolve(webSrc, "routes/EvolutionRoute.tsx"), "utf-8");
    expect(evolution).toContain("usePersistedPaneHeight");
    expect(evolution).toContain("PaneHeightResizeHandle");
    expect(evolution).not.toContain("beginPaneHeightResize");
  });

  it("keeps Memory graph node list on shared height resize handle (Wave 6B)", () => {
    const graph = readFileSync(resolve(webSrc, "routes/MemoryGraphViewPanel.tsx"), "utf-8");
    expect(graph).toContain("usePersistedPaneHeight");
    expect(graph).toContain("PaneHeightResizeHandle");
    expect(graph).toContain("graph-node-list");
    expect(graph).toContain("WORKBENCH_LAYOUT_IDS.memory");
    expect(graph).not.toContain("beginPaneHeightResize");
  });

  it("keeps Logs package-files and Launcher diagnostics on shared height resize (Wave 6C)", () => {
    const logs = readFileSync(resolve(webSrc, "routes/LogsRoute.tsx"), "utf-8");
    const launcherDiag = readFileSync(resolve(webSrc, "routes/LauncherDiagnosticsPanel.tsx"), "utf-8");
    expect(logs).toContain("usePersistedPaneHeight");
    expect(logs).toContain("PaneHeightResizeHandle");
    expect(logs).toContain("package-files");
    expect(logs).toContain("WORKBENCH_LAYOUT_IDS.logs");
    expect(launcherDiag).toContain("usePersistedPaneHeight");
    expect(launcherDiag).toContain("PaneHeightResizeHandle");
    expect(launcherDiag).toContain("diagnostics-body");
    expect(launcherDiag).toContain("WORKBENCH_LAYOUT_IDS.launcher");
  });

  it("keeps Agents/Teams/Memory domain recipe markers (Wave 6B)", () => {
    const agents = readFileSync(resolve(webSrc, "routes/AgentsRoute.tsx"), "utf-8");
    const agentsWorkspace = readFileSync(resolve(webSrc, "routes/AgentWorkspaceLayoutPanel.tsx"), "utf-8");
    const teams = readFileSync(resolve(webSrc, "routes/TeamsRoute.tsx"), "utf-8");
    const memory = readFileSync(resolve(webSrc, "routes/MemoryRoute.tsx"), "utf-8");
    expect(agents).toContain('data-vui-recipe="agents-management-workbench"');
    expect(agentsWorkspace).toContain('data-vui-region="agents-directory"');
    expect(teams).toContain('data-vui-recipe="teams-organization-workbench"');
    expect(teams).toContain('data-vui-region="teams-canvas"');
    expect(memory).toContain('data-vui-domain-recipe="memory-knowledge-workbench"');
    expect(memory).toContain('data-vui-recipe="memory-knowledge-workbench"');
  });

  it("keeps route resize class maps placement-only (Wave 6A)", () => {
    const samples: Array<{ file: string; key: string }> = [
      { file: "routes/GitRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/SupervisedReviewRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/SelfEvolutionTrack.styles.ts", key: "sidebarResizer" },
      { file: "routes/EvolutionRoute.styles.ts", key: "liveIoResizeHandle" },
      { file: "routes/LogsRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/ToolsRoute.styles.ts", key: "resizeHandle" },
      { file: "routes/LauncherRoute.styles.ts", key: "railResizeHandle" },
      { file: "routes/ConfigRoute.styles.ts", key: "settingsNavResizeHandle" },
      { file: "routes/MemoryGraphViewPanel.styles.ts", key: "graphNodeListResizeHandle" },
      { file: "routes/LogsRoute.styles.ts", key: "packageFilesResizeHandle" },
      { file: "routes/LauncherDiagnosticsPanel.styles.ts", key: "diagnosticsBodyResizeHandle" },
    ];

    for (const sample of samples) {
      const text = readFileSync(resolve(webSrc, sample.file), "utf-8");
      // Key assignment should not reintroduce private lit-rule / col-resize chrome.
      const keyBlock = text.match(new RegExp(`${sample.key}:\\s*(?:\`[^\`]*\`|"[^"]*"|'[^']*')`, "m"));
      expect(keyBlock, `${sample.file} ${sample.key}`).not.toBeNull();
      const value = keyBlock?.[0] ?? "";
      expect(value, `${sample.file} ${sample.key} must not own col-resize chrome`).not.toMatch(/cursor-col-resize/);
      expect(value, `${sample.file} ${sample.key} must not own row-resize chrome`).not.toMatch(/cursor-row-resize/);
      expect(value, `${sample.file} ${sample.key} must not paint private before: rule`).not.toMatch(/before:w-/);
    }

    const configStyles = readFileSync(resolve(webSrc, "routes/ConfigRoute.styles.ts"), "utf-8");
    expect(configStyles).not.toContain("sidebarResizeX");
    expect(configStyles).not.toContain("sidebarResizeY");
    expect(configStyles).not.toContain("sidebarResizeCorner");
  });
});
