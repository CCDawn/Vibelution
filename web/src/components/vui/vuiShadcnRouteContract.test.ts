import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Forced frontend contract: routes compose VUI product API only.
 * shadcn/Radix lives under components/vui/renderers/shadcn — never imported from routes.
 */
const webSrc = resolve(import.meta.dirname, "../..");
const routesDir = resolve(webSrc, "routes");

const FORBIDDEN_IMPORT_PATTERNS: Array<{ label: string; re: RegExp }> = [
  { label: "@heroui/react", re: /from\s+["']@heroui\/react["']/ },
  { label: "renderers/shadcn direct", re: /from\s+["'][^"']*renderers\/shadcn[^"']*["']/ },
  { label: "components/ui shadcn bypass", re: /from\s+["'][^"']*\/components\/ui\// },
];

function walkTsFiles(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      walkTsFiles(full, out);
      continue;
    }
    if (/\.(tsx|ts)$/.test(name) && !name.includes(".test.") && !name.includes(".styles.")) {
      out.push(full);
    }
  }
  return out;
}

describe("VUI shadcn route contract", () => {
  it("forbids routes from importing HeroUI or shadcn renderers directly", () => {
    const files = walkTsFiles(routesDir);
    const offenders: string[] = [];

    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      for (const rule of FORBIDDEN_IMPORT_PATTERNS) {
        if (rule.re.test(text)) {
          offenders.push(`${relative(webSrc, file)}: ${rule.label}`);
        }
      }
    }

    expect(offenders, `Forbidden imports in routes:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("keeps project AGENTS.md frontend red line and standards route for VUI/shadcn", () => {
    // webSrc = web/src; project root is two levels up from web/src.
    const projectRoot = resolve(webSrc, "../..");
    const agents = readFileSync(resolve(projectRoot, "AGENTS.md"), "utf-8");
    const standardsIndex = readFileSync(resolve(projectRoot, "docs/standards/README.md"), "utf-8");
    const development = readFileSync(resolve(projectRoot, "docs/standards/development-standard.md"), "utf-8");
    expect(agents).toContain("前端产品 UI 强制 VUI + shadcn/Radix");
    expect(agents).toContain("vuiShadcnRouteContract.test.ts");
    // standards index links the gate by short name or full path
    expect(
      standardsIndex.includes("vuiShadcnRouteContract")
      || standardsIndex.includes("vuiShadcnRouteContract.test.ts"),
    ).toBe(true);
    expect(development).toContain("Hard product constraint");
    expect(development).toContain("vuiShadcnRouteContract.test.ts");
  });

  it("keeps Teams shell on board/canvas page recipes + WORKBENCH_LAYOUT_IDS.teams", () => {
    // TeamsRoute.tsx is a thin re-export; recipe ownership lives in teams/* workbench layers.
    const teamsEntry = readFileSync(resolve(routesDir, "TeamsRoute.tsx"), "utf-8");
    expect(teamsEntry).toMatch(/from\s+["']\.\/teams\/TeamsRouteWorkbench["']/);
    expect(teamsEntry).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(teamsEntry).not.toMatch(/renderers\/shadcn/);

    // Recipe ownership: board page renderer + canvas composer (model entry is a thin lazy shell).
    const workbenchEntry = readFileSync(resolve(routesDir, "teams/useTeamsWorkbenchModel.tsx"), "utf-8");
    const boardPage = readFileSync(resolve(routesDir, "teams/renderTeamsWorkbenchBoardPage.tsx"), "utf-8");
    const canvasComposer = readFileSync(resolve(routesDir, "teams/TeamsCanvasComposer.tsx"), "utf-8");
    const shellFrame = readFileSync(resolve(routesDir, "teams/renderTeamsShellFrame.tsx"), "utf-8");
    const chrome = readFileSync(resolve(routesDir, "teams/teamsWorkbenchChrome.ts"), "utf-8");

    expect(workbenchEntry).toContain("useTeamsWorkbenchFoundation");
    expect(boardPage).toContain("VBoardWorkbenchPage");
    expect(canvasComposer).toContain("VCanvasWorkbenchPage");
    expect(chrome).toContain("WORKBENCH_LAYOUT_IDS.teams");
    expect(canvasComposer).toContain('domainRecipe="teams-organization-workbench"');
    expect(shellFrame).toContain("TeamShellRail");
    expect(workbenchEntry).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(workbenchEntry).not.toMatch(/renderers\/shadcn/);
    expect(boardPage).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(boardPage).not.toMatch(/renderers\/shadcn/);
  });

  it("documents V vs VNative button selection for agents", () => {
    const projectRoot = resolve(webSrc, "../..");
    const actions = readFileSync(
      resolve(webSrc, "components/vui/designs/primitives/actions.md"),
      "utf-8",
    );
    const guide = readFileSync(
      resolve(projectRoot, "docs/guides/button-selection.md"),
      "utf-8",
    );
    expect(actions).toContain("## VButton");
    expect(actions).toContain("## VNativeButton");
    expect(actions).toContain("画布节点");
    expect(guide).toContain("VButton");
    expect(guide).toContain("VNativeButton");
    expect(guide).toContain("<button>");
    expect(guide).toContain("禁止第三套");
  });

  it("forbids raw <button> tags in routes product sources", () => {
    // Prefer VButton / VNativeButton. Implementors of VNativeButton live under components/vui.
    const files = walkTsFiles(routesDir);
    const offenders: string[] = [];
    for (const file of files) {
      const text = readFileSync(file, "utf-8");
      if (/<button[\s>]/.test(text)) {
        offenders.push(relative(webSrc, file));
      }
    }
    expect(offenders, `Raw <button> in routes:\n${offenders.join("\n")}`).toEqual([]);
  });

  it("keeps Chat and Agents workbench recipe markers and layout ids", () => {
    // ChatCodingRoute.tsx is a thin re-export (R01); recipe ownership lives in workbench.
    const chatEntry = readFileSync(resolve(routesDir, "ChatCodingRoute.tsx"), "utf-8");
    expect(chatEntry).toMatch(/from\s+["']\.\/chat\/ChatCodingRouteWorkbench["']/);
    expect(chatEntry.split(/\r?\n/).length).toBeLessThan(40);

    const chat = readFileSync(resolve(routesDir, "chat/ChatCodingRouteWorkbench.tsx"), "utf-8");
    expect(chat).toContain('data-vui-recipe="chat-session-workbench"');
    expect(chat).toContain("WORKBENCH_LAYOUT_IDS.chat");
    expect(chat).not.toMatch(/from\s+["']@heroui\/react["']/);
    expect(chat).not.toMatch(/renderers\/shadcn/);

    const agents = readFileSync(resolve(routesDir, "AgentsRoute.tsx"), "utf-8");
    expect(agents).toContain('data-vui-recipe="agents-management-workbench"');
    expect(agents).toContain("AgentWorkspaceLayoutPanel");
    expect(agents).not.toMatch(/from\s+["']@heroui\/react["']/);

    const agentLayout = readFileSync(resolve(routesDir, "AgentWorkspaceLayoutPanel.tsx"), "utf-8");
    expect(agentLayout).toContain("VListDetailPage");
    expect(agentLayout).toContain("WORKBENCH_LAYOUT_IDS.agents");
  });
});
