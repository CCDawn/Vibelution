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
});
