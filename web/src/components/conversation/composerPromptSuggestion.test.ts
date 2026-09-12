import { describe, expect, it } from "vitest";

import chatRouteSource from "../../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import chatComposerPlusMenuSource from "../../routes/chat/ChatComposerPlusMenu.tsx?raw";
import chatComposerSubmitModelSource from "../../routes/chat/chatComposerSubmitModel.ts?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  resolveComposerGhost,
  resolveComposerPlaceholder,
  shouldAcceptComposerGhost,
  shouldLoadComposerExample,
  shouldRequestComposerPromptSuggestion,
} from "./composerPromptSuggestionModel";
import { promptSuggestionToggleStorageKey } from "../../routes/chat/chatComposerSubmitModel";

describe("composerPromptSuggestionModel", () => {
  it("requests exactly once per turn for the idle empty composer", () => {
    const base = {
      enabled: true,
      sessionId: "session-1",
      busy: false,
      draft: "",
      hasConversation: true,
      issued: false,
    };
    expect(shouldRequestComposerPromptSuggestion(base)).toBe(true);
    expect(shouldRequestComposerPromptSuggestion({ ...base, issued: true })).toBe(false);
    expect(shouldRequestComposerPromptSuggestion({ ...base, enabled: false })).toBe(false);
    expect(shouldRequestComposerPromptSuggestion({ ...base, busy: true })).toBe(false);
    expect(shouldRequestComposerPromptSuggestion({ ...base, draft: "继续" })).toBe(false);
    expect(shouldRequestComposerPromptSuggestion({ ...base, hasConversation: false })).toBe(false);
    expect(shouldRequestComposerPromptSuggestion({ ...base, sessionId: "" })).toBe(false);
  });

  it("loads the starter example only for a thread without turns", () => {
    expect(shouldLoadComposerExample({ enabled: true, sessionId: "s", hasConversation: false })).toBe(true);
    expect(shouldLoadComposerExample({ enabled: true, sessionId: "s", hasConversation: true })).toBe(false);
    expect(shouldLoadComposerExample({ enabled: false, sessionId: "s", hasConversation: false })).toBe(false);
  });

  it("hides the ghost while busy or after typing", () => {
    expect(resolveComposerGhost({ suggestion: " 跑测试 ", draft: "", busy: false })).toBe("跑测试");
    expect(resolveComposerGhost({ suggestion: "跑测试", draft: "x", busy: false })).toBe("");
    expect(resolveComposerGhost({ suggestion: "跑测试", draft: "", busy: true })).toBe("");
  });

  it("renders the ghost with the Tab hint and the starter example before any turn", () => {
    expect(resolveComposerPlaceholder({
      ghost: "跑一下测试",
      exampleCommand: "修复 lint 报错",
      hasConversation: true,
      lang: "zh",
      fallback: "发送消息",
    })).toBe("跑一下测试（Tab 补全）");
    expect(resolveComposerPlaceholder({
      ghost: "run the tests",
      exampleCommand: "",
      hasConversation: true,
      lang: "en",
      fallback: "Message",
    })).toBe("run the tests (Tab to complete)");
    expect(resolveComposerPlaceholder({
      ghost: "",
      exampleCommand: "修复 lint 报错",
      hasConversation: false,
      lang: "zh",
      fallback: "发送消息",
    })).toBe("试试 “修复 lint 报错”");
    expect(resolveComposerPlaceholder({
      ghost: "",
      exampleCommand: "修复 lint 报错",
      hasConversation: true,
      lang: "zh",
      fallback: "发送消息",
    })).toBe("发送消息");
  });

  it("accepts only bare Tab or ArrowRight while the ghost is visible", () => {
    const base = { ghost: "下一步", key: "Tab", shiftKey: false, ctrlKey: false, metaKey: false, altKey: false };
    expect(shouldAcceptComposerGhost(base)).toBe(true);
    expect(shouldAcceptComposerGhost({ ...base, key: "ArrowRight" })).toBe(true);
    expect(shouldAcceptComposerGhost({ ...base, ghost: "" })).toBe(false);
    expect(shouldAcceptComposerGhost({ ...base, shiftKey: true })).toBe(false);
    expect(shouldAcceptComposerGhost({ ...base, key: "ArrowDown" })).toBe(false);
    expect(shouldAcceptComposerGhost({ ...base, ctrlKey: true })).toBe(false);
  });

  it("keys the per-session toggle without leaking across sessions", () => {
    expect(promptSuggestionToggleStorageKey("abc")).toBe("vibelution.chat.promptSuggestionEnabled:abc");
    expect(promptSuggestionToggleStorageKey("abc")).not.toBe(promptSuggestionToggleStorageKey("def"));
  });
});

describe("composer prompt suggestion wiring", () => {
  it("wires the toggle, the hook, and the ghost surface through the real components", () => {
    expect(chatComposerPlusMenuSource).toContain('id: "prompt-suggestion"');
    expect(chatComposerPlusMenuSource).toContain("onPromptSuggestionEnabledChange");
    expect(chatComposerSubmitModelSource).toContain('PROMPT_SUGGESTION_TOGGLE_STORAGE_PREFIX = "vibelution.chat.promptSuggestionEnabled:"');
    expect(chatRouteSource).toContain("readStoredPromptSuggestionToggle");
    expect(chatRouteSource).toContain("writeStoredPromptSuggestionToggle");
    expect(chatRouteSource).toContain("promptSuggestionEnabled={activePromptSuggestionEnabled}");
    expect(chatRouteSource).toContain("promptSuggestionEnabled: activePromptSuggestionEnabled,");
    expect(conversationViewSource).toContain("useComposerPromptSuggestion(");
    expect(conversationViewSource).toContain("shouldAcceptComposerGhost(");
    expect(conversationViewSource).toContain("data-composer-prompt-suggestion");
  });
});
