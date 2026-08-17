import ts from "typescript";
import { describe, expect, it } from "vitest";

import { routeLocationKey } from "./AppShell";
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

function collectWindowHistoryCalls(source: ts.SourceFile): string[] {
  const calls: string[] = [];

  function visit(node: ts.Node) {
    if (
      ts.isCallExpression(node)
      && ts.isPropertyAccessExpression(node.expression)
      && ["pushState", "replaceState", "go", "back", "forward"].includes(node.expression.name.text)
      && isWindowHistoryExpression(node.expression.expression)
    ) {
      calls.push(node.expression.getText(source));
    }
    ts.forEachChild(node, visit);
  }

  visit(source);
  return calls;
}

/** Extract the body of a named function declaration by simple source slicing. */
function functionBody(source: string, functionName: string): string {
  const marker = `function ${functionName}`;
  const start = source.indexOf(marker);
  if (start < 0) {
    return "";
  }
  const bodyStart = source.indexOf("{", start);
  if (bodyStart < 0) {
    return "";
  }
  let depth = 0;
  for (let index = bodyStart; index < source.length; index += 1) {
    if (source[index] === "{") depth += 1;
    if (source[index] === "}") {
      depth -= 1;
      if (depth === 0) {
        return source.slice(bodyStart, index + 1);
      }
    }
  }
  return "";
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

function collectRouteLinksUsingDocumentReload(source: ts.SourceFile, paths: Set<string>): string[] {
  const usingReload: string[] = [];
  const routeLinkTags = new Set(["NavLink", "VRouteLinkButton", "Link"]);

  function visit(node: ts.Node) {
    if (ts.isJsxOpeningElement(node) || ts.isJsxSelfClosingElement(node)) {
      const tagName = node.tagName.getText(source);
      if (routeLinkTags.has(tagName)) {
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
  it("keeps a passive route location key helper without desync authority", () => {
    expect(routeLocationKey({ pathname: "", search: "", hash: "" })).toBe("/");
    expect(routeLocationKey({ pathname: "/teams", search: "?agent=agent-1", hash: "#members" }))
      .toBe("/teams?agent=agent-1#members");
  });

  it("contains no router desync recovery symbols, plan, or telemetry event", () => {
    expect(appShellSource).not.toContain("routerLocationDesyncTarget");
    expect(appShellSource).not.toContain("routerLocationDesyncRecoveryPlan");
    expect(appShellSource).not.toContain("RouterLocationDesyncRecoveryPlan");
    expect(appShellSource).not.toContain("recoverRouterLocationDesync");
    expect(appShellSource).not.toContain("ROUTER_LOCATION_DESYNC_RECOVERY_DELAY_MS");
    expect(appShellSource).not.toContain("lastRouterLocationDesyncTargetRef");
    expect(appShellSource).not.toContain("scheduleRecovery");
    expect(appShellSource).not.toContain("browser.router_location_desync.recovered");
    expect(appShellSource).not.toContain("browser.router_location_desync");
    expect(appShellSource).not.toContain("router_location_desync");
  });

  it("does not call window.history methods from the app shell", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(collectHistoryMonkeyPatches(source)).toEqual([]);
    expect(collectWindowHistoryCalls(source)).toEqual([]);
    expect(appShellSource).not.toContain("window.history.pushState");
    expect(appShellSource).not.toContain("window.history.replaceState");
    expect(appShellSource).not.toContain("window.history.go");
  });

  it("never navigates from focus or pageshow handlers", () => {
    // The desync recovery effect was the only focus/pageshow consumer in the shell.
    expect(appShellSource).not.toContain('window.addEventListener("focus"');
    expect(appShellSource).not.toContain('window.addEventListener("pageshow"');
    expect(appShellSource).not.toContain('window.removeEventListener("focus"');
    expect(appShellSource).not.toContain('window.removeEventListener("pageshow"');
  });

  it("keeps the visibilitychange handler telemetry-only (no navigate, no History API)", () => {
    const visibilityBody = functionBody(appShellSource, "handleVisibilityChange");
    expect(visibilityBody).toContain("browser.visibility.changed");
    expect(visibilityBody).toContain("setFrontendVisible");
    expect(visibilityBody).not.toContain("navigate(");
    expect(visibilityBody).not.toContain("window.history");
    expect(visibilityBody).not.toContain("setSearchParams");
  });

  it("keeps popstate telemetry passive without navigation repair", () => {
    const popStateBody = functionBody(appShellSource, "handlePopState");
    expect(popStateBody).toContain("browser.history.pop_state");
    expect(popStateBody).not.toContain("navigate(");
    expect(popStateBody).not.toContain("window.history");
  });

  it("intercepts Electron shell navigation anchors with capture-phase SPA navigation", () => {
    // Recovery was removed, but the Electron title-bar/hit-test protection must stay.
    expect(appShellSource).toContain("shellNavAnchorFromEventTarget");
    expect(appShellSource).toContain("resolveUnmodifiedShellNavHref");
    expect(appShellSource).toContain("navigatePrimaryNav(to)");
    expect(appShellSource).toContain('window.addEventListener("click", handleDocumentClick, true)');
    expect(appShellSource).toContain('window.removeEventListener("click", handleDocumentClick, true)');
    expect(appShellSource).toContain("event.preventDefault()");
    expect(appShellSource).toContain("event.defaultPrevented");
  });

  it("uses client-side navigation for global page switches", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(
      collectRouteLinksUsingDocumentReload(
        source,
        new Set(["/chat", "/supervised-evolution", "/self-evolution", "/teams", "/memory", "/agents", "/logs", "/git", "/config"]),
      ),
    ).toEqual([]);
    expect(appShellSource).toContain('chrome="shell-nav"');
    expect(appShellSource).not.toContain("<NavLink");
  });

  it("preloads the chat route from navigation before the user waits on the route chunk", () => {
    expect(appShellSource).toContain("function preloadChatRouteForNav");
    expect(appShellSource).toContain("browser.chat_route.preload_requested");
    expect(appShellSource).toContain("browser.chat_route.preload_loaded");
    expect(appShellSource).toContain("browser.chat_route.preload_failed");
    expect(appShellSource).toContain('import("../routes/ChatCodingRoute")');
    // F1: soft idle preload on hover/focus; hard immediate on click.
    expect(appShellSource).toContain("requestIdleCallback");
    expect(appShellSource).toContain("cancelChatRouteSoftPreload");
    expect(appShellSource).toContain("startChatRoutePreloadImport");
    expect(appShellSource).toContain('onPointerEnter={() => preloadChatRouteForNav("pointerenter")}');
    expect(appShellSource).toContain('onFocus={() => preloadChatRouteForNav("focus")}');
    expect(appShellSource).toContain('onClick={(event) => handlePrimaryNavClick(event, "/chat")}');
    expect(appShellSource).toContain("handlePrimaryNavClick");
    expect(appShellSource).toContain("browser.primary_nav.click");
  });

  it("keeps group chat out of the top navigation because it lives in the chat page", () => {
    expect(appShellSource).not.toContain('to="/chat-rooms"');
    expect(appShellSource).not.toContain('t("navChatRooms")');
  });

  it("does not embed a file tree or chat shortcut in the workbench utility menu", () => {
    expect(appShellSource).toContain("LazyAppShellUtilityMenu");
    expect(appShellSource).not.toContain("filterUtilityFileTree");
    expect(appShellSource).not.toContain("renderUtilityFileTree");
    expect(utilityMenuSource).toContain('from "./AppShellUtilityMenu.styles"');
    expect(utilityMenuSource).not.toContain("AppShell.styles");
    expect(utilityMenuSource).not.toContain("filterUtilityFileTree");
    expect(utilityMenuSource).not.toContain("renderUtilityFileTree");
    expect(utilityMenuSource).not.toContain("utility-file-navigator");
    expect(utilityMenuSource).not.toContain('to="/chat"');
    expect(utilityMenuSource).not.toContain("{t(\"files\")}");
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
