import { describe, expect, it } from "vitest";

import {
  classifyConversationMarkdownLinkTarget,
  normalizeMarkdownFilePath,
} from "./conversationMarkdownLinkTargets";

describe("classifyConversationMarkdownLinkTarget", () => {
  it("classifies http/https/mailto hrefs as external and keeps the URL", () => {
    expect(classifyConversationMarkdownLinkTarget("https://example.com/a.png")).toEqual({
      kind: "external",
      url: "https://example.com/a.png",
    });
    expect(classifyConversationMarkdownLinkTarget("http://localhost:3000/api/x")).toEqual({
      kind: "external",
      url: "http://localhost:3000/api/x",
    });
    expect(classifyConversationMarkdownLinkTarget("MAILTO:dev@example.com")).toEqual({
      kind: "external",
      url: "MAILTO:dev@example.com",
    });
    expect(classifyConversationMarkdownLinkTarget("  https://example.com/b  ")).toEqual({
      kind: "external",
      url: "https://example.com/b",
    });
  });

  it("classifies absolute Windows drive and UNC paths as workspace files", () => {
    expect(classifyConversationMarkdownLinkTarget("C:\\repo\\web\\src\\App.tsx")).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\web\\src\\App.tsx",
    });
    expect(classifyConversationMarkdownLinkTarget("C:/repo/docs/介绍.md")).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\docs\\介绍.md",
    });
    expect(classifyConversationMarkdownLinkTarget("\\\\server\\share\\file.md")).toEqual({
      kind: "workspace-file",
      absolutePath: "\\\\server\\share\\file.md",
    });
  });

  it("resolves root-relative, dot-relative and file-like relative hrefs against the workspace root", () => {
    const root = "C:\\repo";
    expect(classifyConversationMarkdownLinkTarget("/src/index.ts", root)).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\src\\index.ts",
    });
    expect(classifyConversationMarkdownLinkTarget("./docs/spec.md", root)).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\docs\\spec.md",
    });
    expect(classifyConversationMarkdownLinkTarget("../shared/lib.py", "C:\\repo\\web")).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\shared\\lib.py",
    });
    expect(classifyConversationMarkdownLinkTarget("web/src/App.tsx", root)).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\repo\\web\\src\\App.tsx",
    });
    expect(classifyConversationMarkdownLinkTarget("docs/介绍.md", "/home/u/proj")).toEqual({
      kind: "workspace-file",
      absolutePath: "/home/u/proj/docs/介绍.md",
    });
  });

  it("decodes percent escapes in workspace file paths", () => {
    expect(classifyConversationMarkdownLinkTarget("docs/%E4%BB%8B%E7%BB%8D.md", "/h/p")).toEqual({
      kind: "workspace-file",
      absolutePath: "/h/p/docs/介绍.md",
    });
    expect(classifyConversationMarkdownLinkTarget("my%20notes.md", "C:\\r")).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\r\\my notes.md",
    });
  });

  it("keeps unresolvable paths and non-file shapes inert", () => {
    const other = (href: string, root?: string) => classifyConversationMarkdownLinkTarget(href, root);
    // No workspace root → cannot become absolute → legacy anchor behavior.
    expect(other("/src/index.ts")).toEqual({ kind: "other", raw: "/src/index.ts" });
    expect(other("web/src/App.tsx")).toEqual({ kind: "other", raw: "web/src/App.tsx" });
    expect(other("./a.md")).toEqual({ kind: "other", raw: "./a.md" });
    // Non-file shapes.
    expect(other("#anchor", "C:\\r").kind).toBe("other");
    expect(other("//cdn.example.com/x.js", "C:\\r").kind).toBe("other");
    expect(other("docs/", "C:\\r").kind).toBe("other");
    expect(other("src", "C:\\r").kind).toBe("other");
    expect(other("v1.2", "C:\\r").kind).toBe("other");
    expect(other("8.1 release", "C:\\r").kind).toBe("other");
    expect(other("path?a=1.md", "C:\\r").kind).toBe("other");
    expect(other("path#frag.md", "C:\\r").kind).toBe("other");
    // Unknown / unsafe schemes.
    expect(other("javascript:alert(1)", "C:\\r").kind).toBe("other");
    expect(other("data:text/plain,x", "C:\\r").kind).toBe("other");
    expect(other("C:", "C:\\r").kind).toBe("other");
    // Whitespace and control characters never become paths.
    expect(other("a b.md", "C:\\r").kind).toBe("other");
    expect(other("", "C:\\r").kind).toBe("other");
  });

  it("keeps multi-extension and lettered numeric tails file-like", () => {
    expect(classifyConversationMarkdownLinkTarget("archive.tar.gz", "C:\\r")).toEqual({
      kind: "workspace-file",
      absolutePath: "C:\\r\\archive.tar.gz",
    });
  });
});

describe("normalizeMarkdownFilePath", () => {
  it("normalizes separators and resolves dot segments lexically", () => {
    expect(normalizeMarkdownFilePath("C:\\a\\b\\..\\c\\.\\d.md")).toBe("C:\\a\\c\\d.md");
    expect(normalizeMarkdownFilePath("C:/a/b/../c.md")).toBe("C:\\a\\c.md");
    expect(normalizeMarkdownFilePath("/a/./b/../c.md")).toBe("/a/c.md");
    expect(normalizeMarkdownFilePath("a/b/c.md")).toBe("a/b/c.md");
    expect(normalizeMarkdownFilePath("../up.md", "C:\\base")).toBe("up.md");
  });

  it("preserves the UNC prefix while normalizing the body", () => {
    expect(normalizeMarkdownFilePath("\\\\server\\share\\..\\file.md")).toBe("\\\\server\\file.md");
  });
});
