import { describe, expect, it } from "vitest";

import conversationMarkdownRendererSource from "./ConversationMarkdownRenderer.tsx?raw";
import { safeConversationMarkdownUrl } from "./conversationMarkdownUrl";

describe("safeConversationMarkdownUrl", () => {
  it("allows http, https, and relative markdown URLs", () => {
    expect(safeConversationMarkdownUrl("https://example.com/a.png")).toBe("https://example.com/a.png");
    expect(safeConversationMarkdownUrl("http://example.com/a")).toBe("http://example.com/a");
    expect(safeConversationMarkdownUrl("/api/sessions/s1/artifacts/a.png")).toBe("/api/sessions/s1/artifacts/a.png");
    expect(safeConversationMarkdownUrl("./images/a.png")).toBe("./images/a.png");
    expect(safeConversationMarkdownUrl("../images/a.png")).toBe("../images/a.png");
    expect(safeConversationMarkdownUrl("#section")).toBe("#section");
    expect(safeConversationMarkdownUrl("docs/page.md")).toBe("docs/page.md");
  });

  it("rejects executable, control-character, and ambiguous markdown URLs", () => {
    expect(safeConversationMarkdownUrl("javascript:alert(1)")).toBeNull();
    expect(safeConversationMarkdownUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
    expect(safeConversationMarkdownUrl("vbscript:msgbox(1)")).toBeNull();
    expect(safeConversationMarkdownUrl("file:///C:/secret.txt")).toBeNull();
    expect(safeConversationMarkdownUrl("//evil.example/a.png")).toBeNull();
    expect(safeConversationMarkdownUrl("java\nscript:alert(1)")).toBeNull();
    expect(safeConversationMarkdownUrl("https://example.com/a b.png")).toBeNull();
    expect(safeConversationMarkdownUrl("")).toBeNull();
  });

  it("keeps markdown URL safety in the shared markdown renderer", () => {
    expect(conversationMarkdownRendererSource).toContain('from "./conversationMarkdownUrl"');
    expect(conversationMarkdownRendererSource).not.toMatch(/export function safeConversationMarkdownUrl|function safeConversationMarkdownUrl/);
  });
});
