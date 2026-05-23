import ts from "typescript";
import { describe, expect, it } from "vitest";

import appShellSource from "./AppShell.tsx?raw";

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
  it("does not monkey-patch router-owned browser history methods", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(collectHistoryMonkeyPatches(source)).toEqual([]);
  });

  it("uses client-side navigation for global page switches", () => {
    const source = ts.createSourceFile("AppShell.tsx", appShellSource, ts.ScriptTarget.Latest, true, ts.ScriptKind.TSX);

    expect(
      collectNavLinksUsingDocumentReload(
        source,
        new Set(["/chat", "/supervised-evolution", "/self-evolution", "/logs", "/tools", "/git", "/memory", "/config"]),
      ),
    ).toEqual([]);
  });
});
