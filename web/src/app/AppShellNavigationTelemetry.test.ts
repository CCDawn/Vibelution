import ts from "typescript";
import { describe, expect, it } from "vitest";

import { routeLocationKey, routerLocationDesyncRecoveryPlan, routerLocationDesyncTarget } from "./AppShell";
import appShellSource from "./AppShell.tsx?raw";
import utilityMenuSource from "./AppShellUtilityMenu.tsx?raw";

function isWindowHistoryExpression(node: ts.Expression): boolean {
  return ts.isPropertyAccessExpression(node)
    && node.name.text === "history"
    && ts.isIdentifier(node.expression)
    && node.expression.text === "window";
}

function collectHistoryMonkeyPatches(source: ts.SourceFile): string[] {
  const assignments: string[] = [];

  function visit(node: ts.Node) {
    if (
      ts.isBinaryExpression(node)
      && node.operatorToken.kind === ts.SyntaxKind.EqualsToken
      && ts.isPropertyAccessExpression(node.left)
      && ["pushState", "replaceState"].includes(node.left.name.text)
      && isWindowHistoryExpression(node.left.expression)
    ) {
      assignments.push(node.left.getText(source));
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
  return assignments;
}

function getStringAttributeValue(attribute: ts.JsxAttribute): string | null {
  const initializer = attribute.initializer;
  if (!initializer) {
    return "";
  }
  if (ts.isStringLiteral(initializer)) {
    return initializer.text;
  }
  return null;
}

function collectNavLinksUsingDocumentReload(source: ts.SourceFile, paths: Set<string>): string[] {
  const usingReload: string[] = [];

  function visit(node: ts.Node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tagName = node.tagName.getText(source);
      if (tagName === "NavLink") {
        let toPath: string | null = null;
        let hasReloadDocument = false;
        for (const property of node.attributes.properties) {
          if (!ts.isJsxAttribute(property)) {
            continue;
          }
          if (!ts.isIdentifier(property.name)) {
            continue;
          }
          if (property.name.text === "to") {
            toPath = getStringAttributeValue(property);
          }
          if (property.name.text === "reloadDocument") {
            hasReloadDocument = true;
          }
        }
        if (toPath && paths.has(toPath) && hasReloadDocument) {
          usingReload.push(toPath);
        }
      }
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
  return usingReload;
}

describe("AppShell navigation telemetry", () => {
  it("detects browser/router location desync targets without touching aligned routes", () => {
    expect(
      routerLocationDesyncTarget(
        { pathname: "/teams", search: "", hash: "" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toBe("/teams");
    expect(
      routerLocationDesyncTarget(
        { pathname: "/teams", search: "?agent=agent-1", hash: "#members" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toBe("/teams?agent=agent-1#members");
    expect(
      routerLocationDesyncTarget(
        { pathname: "/agents", search: "", hash: "" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toBeNull();
    expect(routeLocationKey({ pathname: "", search: "", hash: "" })).toBe("/");
  });

  it("plans a two-step recovery when the browser URL already moved outside the router", () => {
    expect(
      routerLocationDesyncRecoveryPlan(
        { pathname: "/teams", search: "", hash: "" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toEqual({
      target: "/teams",
      restoreTarget: "/agents",
    });
    expect(
      routerLocationDesyncRecoveryPlan(
        { pathname: "/self-evolution", search: "?run=1", hash: "#events" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toEqual({
      target: "/self-evolution?run=1#events",
      restoreTarget: "/agents",
    });
    expect(
      routerLocationDesyncRecoveryPlan(
        { pathname: "/agents", search: "", hash: "" },
        { pathname: "/agents", search: "", hash: "" },
      ),
    ).toBeNull();
  });

  it("does not monkey-patch router-owned browser history methods", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(collectHistoryMonkeyPatches(source)).toEqual([]);
  });

  it("uses client-side navigation for global page switches", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(
      collectNavLinksUsingDocumentReload(
        source,
        new Set(["/chat", "/supervised-evolution", "/self-evolution", "/teams", "/memory", "/agents", "/logs", "/git", "/config"]),
      ),
    ).toEqual([]);
  });

  it("recovers when the browser address changes without the router location following", () => {
    expect(appShellSource).toContain("routerLocationDesyncRecoveryPlan(window.location, location)");
    expect(appShellSource).toContain("browser.router_location_desync.recovered");
    expect(appShellSource).toContain('window.history.replaceState(window.history.state, "", recovery.restoreTarget)');
    expect(appShellSource).toContain('navigate(target, { replace: true })');
    expect(appShellSource).toContain('window.addEventListener("click", handleDocumentClick, true)');
    expect(appShellSource).toContain('window.removeEventListener("click", handleDocumentClick, true)');
    expect(appShellSource).toContain('document.addEventListener("visibilitychange", handleVisibilityChange)');
    expect(appShellSource).toContain("browserPathnameBefore");
  });

  it("keeps group chat out of the top navigation because it lives in the chat page", () => {
    expect(appShellSource).not.toContain('to="/chat-rooms"');
    expect(appShellSource).not.toContain('t("navChatRooms")');
  });

  it("keeps file navigation inside the workbench utility menu", () => {
    expect(appShellSource).toContain("LazyAppShellUtilityMenu");
    expect(appShellSource).not.toContain("filterUtilityFileTree");
    expect(appShellSource).not.toContain("renderUtilityFileTree");
    expect(utilityMenuSource).toContain("filterUtilityFileTree");
    expect(utilityMenuSource).toContain("renderUtilityFileTree");
    expect(utilityMenuSource).toContain("utility-file-navigator");
    expect(utilityMenuSource).toContain("openPreviewTab(activeSessionId, path)");
    expect(utilityMenuSource).toContain('navigate("/chat")');
  });

  it("keeps Agent management top-level while memory is a separate primary surface", () => {
    expect(appShellSource).not.toContain('to="/agents/tools"');
    expect(appShellSource).not.toContain('to="/tools"');
    expect(appShellSource).not.toContain('to="/skills"');
    expect(appShellSource).toContain('to="/memory"');
    expect(appShellSource).toContain('t("navMemory")');
    expect(appShellSource).toContain('to="/agents"');
    expect(appShellSource).toContain('t("navAgents")');
  });
});
