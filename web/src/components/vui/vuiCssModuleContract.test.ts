import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join, relative, resolve } from "node:path";

import { describe, expect, it } from "vitest";

const sourceRoot = resolve(import.meta.dirname, "../..");

function walkCssModules(dir: string): string[] {
  if (!existsSync(dir)) {
    return [];
  }
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const path = join(dir, entry.name);
    if (entry.isDirectory()) {
      return walkCssModules(path);
    }
    return entry.isFile() && entry.name.endsWith(".module.css") ? [path] : [];
  });
}

function cssModuleSources() {
  return walkCssModules(sourceRoot)
    .sort((left, right) => left.localeCompare(right))
    .map((path) => ({
      path: relative(sourceRoot, path).replaceAll("\\", "/"),
      source: readFileSync(path, "utf8"),
    }));
}

function lineFor(source: string, index: number) {
  return source.slice(0, index).split(/\r?\n/).length;
}

describe("VUI CSS module contract", () => {
  it("keeps route and component CSS modules on semantic visual tokens", () => {
    const modules = cssModuleSources();
    const modulePaths = modules.map(({ path }) => path);

    expect(modules.length).toBeLessThanOrEqual(16);
    expect(modulePaths).not.toContain("app/LauncherShell.module.css");
    expect(modulePaths).not.toContain("app/RouteLoadingShell.module.css");
    expect(modulePaths).not.toContain("app/RouteErrorBoundary.module.css");
    expect(modulePaths).not.toContain("components/layout/PaneCollapseHandle.module.css");
    expect(modulePaths).not.toContain("components/preview/FilePreview.module.css");
    expect(modulePaths).not.toContain("components/preview/StructuredLogPreview.module.css");
    expect(modulePaths).not.toContain("routes/AgentManagementNav.module.css");
    expect(modulePaths).not.toContain("routes/GitDiffView.module.css");
    expect(modulePaths).not.toContain("routes/KernelTaskCenterRoute.module.css");
    expect(modulePaths).not.toContain("routes/PetRoute.module.css");
    expect(modulePaths).not.toContain("routes/PromptTemplatesRoute.module.css");
    expect(modulePaths).not.toContain("routes/ResetRoute.module.css");
    expect(modulePaths).not.toContain("routes/SkillsRoute.module.css");
    expect(modulePaths).not.toContain("routes/SupervisedWorkspaceControls.module.css");
    expect(modulePaths).not.toContain("routes/SupervisedWorkspaceTabs.module.css");
    expect(modulePaths).not.toContain("routes/SupervisedWorktreeReviewPanel.module.css");

    const literalColorOffenders = modules.flatMap(({ path, source }) =>
      [...source.matchAll(/#[0-9a-fA-F]{3,8}|rgba?\(/g)].map((match) => `${path}:${lineFor(source, match.index ?? 0)}`),
    );
    const localGradientOffenders = modules.flatMap(({ path, source }) =>
      [...source.matchAll(/linear-gradient\(/g)].map((match) => `${path}:${lineFor(source, match.index ?? 0)}`),
    );
    const localHeavyShadowOffenders = modules.flatMap(({ path, source }) =>
      [...source.matchAll(/box-shadow\s*:\s*([^;]+);/gs)]
        .filter((match) => {
          const value = match[1].trim();
          return !/^none\b/i.test(value) && !/^var\(--(?:focus-ring|shadow|vui-shadow)/.test(value);
        })
        .map((match) => `${path}:${lineFor(source, match.index ?? 0)}`),
    );

    expect(literalColorOffenders).toEqual([]);
    expect(localGradientOffenders).toEqual([]);
    expect(localHeavyShadowOffenders).toEqual([]);
  });
});
