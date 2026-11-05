/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VuiProvider } from "../../components/vui";
import { ChatComposerPlusMenu, ChatComposerSessionReferencesContext, type ChatComposerPlusMenuProps } from "./ChatComposerPlusMenu";
import type { ChatComposerBudgetControl } from "./ChatComposerBudgetPopover";

import source from "./ChatComposerPlusMenu.tsx?raw";
import stylesSource from "./ChatComposerPlusMenu.styles.ts?raw";
import chatSurfaceSource from "./useChatConversationSurfaceModel.tsx?raw";

describe("ChatComposerPlusMenu contract", () => {
  it("renders grouped sections anchored to the shared composer width", () => {
    expect(stylesSource).toContain("!w-[var(--radix-popover-trigger-width)]");
    expect(source).toContain("anchorRef={hasComposerAnchor ? composerAnchorRef : undefined}");
    expect(stylesSource).toContain('menu: "vui-routes-chatcomposerplusmenu menu grid');
    expect(stylesSource).toContain('sectionTitle: "vui-routes-chatcomposerplusmenu sectionTitle');
    expect(source).toContain('role="menu"');
    expect(source).toContain("chat-composer-plus-${section.id}");
    expect(source).not.toContain("secondaryPanel");
    expect(source).not.toContain("primaryPanel");
    expect(source).not.toContain("ChevronRight");
    expect(source).not.toContain("tertiaryPanel");
    expect(source).not.toContain("thirdPanel");
  });

  it("groups the approved actions and renders capabilities as direct switches", () => {
    expect(source).toContain('label: lang === "zh" ? "添加与引用"');
    expect(source).toContain('label: lang === "zh" ? "对话能力"');
    expect(source).toContain('label: lang === "zh" ? "会话与陪伴"');
    expect(source).toContain('label: lang === "zh" ? "群聊与团队"');
    expect(source).toContain('role="menuitemcheckbox"');
    expect(source).toContain("aria-checked={options.checked}");
    expect(source).toContain('label: lang === "zh" ? "心智模型"');
    expect(source).toContain('label: lang === "zh" ? "运行状态注入"');
    expect(source).toContain('id: "manage-group"');
    expect(source).toContain("<Check");
    // Pet interaction rows retired together with the chat status rail.
    expect(source).not.toContain('id: "companion-feed"');
  });

  it("supports arrow-key navigation across enabled menu items", () => {
    expect(source).toContain('data-plus-menu-item="true"');
    expect(source).toContain('"ArrowDown"');
    expect(source).toContain('"ArrowUp"');
    expect(source).toContain('"Home"');
    expect(source).toContain('"End"');
    expect(source).toContain(":not([disabled])");
  });

  it("keeps slash commands, skills, and cache status out of the plus menu", () => {
    expect(source).not.toContain("slashCommand");
    expect(source).not.toContain("Skill");
    expect(source).not.toContain("缓存状态");
    expect(source).not.toContain("Context cache");
  });

  it("uses VUI overlays for the menu and the reference picker", () => {
    expect(source).toContain("<VPopover");
    expect(source).toContain("<VDialog");
    expect(source).toContain("<VButton");
    expect(source).toContain("<VNativeInput");
  });
  it("offers file attachments and a knowledge/file reference picker", () => {
    expect(source).toContain('id: "reference-knowledge"');
    expect(source).toContain("composerAttachmentAcceptAttribute()");
    expect(source).toContain("knowledgeReferenceOptions");
    expect(source).toContain("onAddKnowledgeReference");
    expect(source).not.toContain('accept="image/png,image/jpeg,image/webp"');
    // Reference pickers rank candidates with the shared tiered matcher.
    expect(source).toContain("conversationFuzzyMatch");
    expect(source).toContain("rankByScore(");
  });

  it("keeps reference pickers as native button lists", () => {
    expect(source).not.toContain('role="listbox"');
    expect(source).not.toContain('role="option"');
  });

  it("gates the budget entry on the injected control and opens it as a side popover", () => {
    expect(source).toContain("<ChatComposerBudgetPopover");
    expect(source).toContain('data-plus-menu-item="true"');
    // Entry presence is prop-gated (group/companion/finance surfaces pass nothing).
    expect(source).toContain("{budget ? (");
  });

  it("gates the private attachment entry on onAttachSecret and keeps the plaintext write-only", () => {
    expect(source).toContain("onAttachSecret?");
    // The menu item only exists when the prop is passed (ordinary chats never pass it).
    expect(source).toContain("{onAttachSecret ? renderAction({");
    expect(source).toContain('id: "attach-secret"');
    // Dialog composition: optional display label + masked value input; any secret rides one
    // shared path, so there is no kind selector.
    expect(source).not.toContain("VStringSelect");
    expect(source).not.toContain("隐私附件类型");
    expect(source).toContain('type="password"');
    expect(source).toContain('autoComplete="new-password"');
    // Every exit burns the in-memory draft; the value never reaches props storage.
    expect(source).toContain("resetSecretDraft()");
    // No persistence, draft or snapshot ever receives the dialog state.
    expect(source).not.toContain("localStorage");
    expect(stylesSource).toContain("secretBody");
  });

  it("never wires the private attachment entry into ordinary chat surfaces", () => {
    // The shared chat surface model mounts the plus menu without the secret prop.
    expect(chatSurfaceSource).not.toContain("onAttachSecret");
  });
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
describe("lazy knowledge picker", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });
  it("anchors inside either shared composer and restores keyboard focus on Escape", async () => {
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    await act(async () => root!.render(<div className="composerCodex"><ChatComposerPlusMenu
      lang="zh" showCapabilities={false} showReferences={false} attachmentDisabled={false}
      sessionReferences={[]} onAddAttachments={vi.fn()}
      onAttachSecret={vi.fn().mockResolvedValue(undefined)} /></div>));
    const trigger = container.querySelector<HTMLButtonElement>('[aria-label="更多操作"]')!;
    await act(async () => { trigger.focus(); trigger.click(); await new Promise(resolve => setTimeout(resolve, 0)); });
    const panel = document.querySelector<HTMLElement>('[data-vui="popover"]')!;
    expect(panel.className).toContain("composerWidth");
    const menu = panel.querySelector<HTMLElement>('[role="menu"]')!;
    const items = [...menu.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]:not([disabled])')];
    expect(items.length).toBeGreaterThan(1);
    await act(async () => items[0].dispatchEvent(new KeyboardEvent("keydown", { key: "End", bubbles: true })));
    expect(document.activeElement).toBe(items.at(-1));
    await act(async () => { menu.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true })); await new Promise(resolve => setTimeout(resolve, 0)); });
    await act(async () => { await new Promise(resolve => setTimeout(resolve, 20)); });
    expect(document.querySelector('[role="menu"]')).toBeNull();
    expect(document.activeElement).toBe(trigger);
  });
  it("offers native assistant budgets without exposing unsupported capability toggles", async () => {
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    await act(async () => root!.render(<ChatComposerPlusMenu lang="zh" showCapabilities={false}
      showReferences={false} attachmentDisabled={false} sessionReferences={[]}
      budget={{ sessionId: "assistant", revision: 3, maxCallsPerTurn: 16, onSave: vi.fn() }} />));
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="更多操作"]')!.click());
    const menu = document.querySelector('[role="menu"]')!;
    expect(menu.textContent).toContain("预算与额度");
    expect(menu.querySelector('[role="menuitemcheckbox"]')).toBeNull();
    const entry = [...menu.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent?.includes("预算与额度"))!;
    await act(async () => entry.click());
    expect(document.querySelector('[data-testid="chat-composer-budget-unlimited"]')).not.toBeNull();
  });
  it("reuses the attachment menu in native hosts without phantom capabilities or references", async () => {
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    const onAddAttachments = vi.fn();
    await act(async () => root!.render(<ChatComposerPlusMenu lang="zh" showCapabilities={false}
      showReferences={false} attachmentDisabled={false} sessionReferences={[]} onAddAttachments={onAddAttachments} />));
    const trigger = container.querySelector<HTMLButtonElement>('button[aria-label="更多操作"]')!;
    await act(async () => trigger.click());
    const menu = document.querySelector('[role="menu"]')!;
    expect(menu.textContent).toContain("附件");
    expect(menu.textContent).not.toContain("引用会话");
    expect(menu.textContent).not.toContain("知识");
    expect(menu.querySelector('[role="menuitemcheckbox"]')).toBeNull();
    const input = container.querySelector<HTMLInputElement>('input[type="file"]')!;
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    Object.defineProperty(input, "files", { configurable: true, value: [file] });
    await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
    expect(onAddAttachments).toHaveBeenCalledExactlyOnceWith([file]);
  });
  it("opens before candidates arrive, shows loading and retry, then selects a reference", async () => {
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    const onRequest = vi.fn();
    const onAdd = vi.fn();
    const reference = { referenceId: "file:one", kind: "file" as const, artifactId: "one", title: "验收文档", createdAt: "2026-10-21T00:00:00Z" };
    const props: ChatComposerPlusMenuProps = {
      lang: "zh", attachmentDisabled: false, sessionReferences: [], onAddKnowledgeReference: onAdd,
      mentalModelEnabled: false, runtimeStatusEnabled: true, promptSuggestionEnabled: true,
      capabilityDisabled: false, onMentalModelEnabledChange: vi.fn(),
      onRuntimeStatusEnabledChange: vi.fn(), onPromptSuggestionEnabledChange: vi.fn(),
    };
    const render = async (loading: boolean, error: boolean, ready = false) => {
      await act(async () => root!.render(<VuiProvider><ChatComposerPlusMenu {...props}
        knowledgeReferenceState={{ loading, error, onRequest }}
        knowledgeReferenceOptions={ready ? [{ id: "one", title: reference.title, reference }] : []} /></VuiProvider>));
    };
    await render(false, false);
    expect(onRequest).not.toHaveBeenCalled();
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="更多操作"]')!.click());
    const action = [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')].find(button => button.textContent?.includes("引用知识/文件"));
    expect(action?.disabled).toBe(false);
    await act(async () => action!.click());
    expect(onRequest).toHaveBeenCalledTimes(1);
    await render(true, false);
    expect(document.querySelector('[role="status"]')?.textContent).toContain("正在加载知识与文件");
    expect(document.body.textContent).not.toContain("没有匹配的知识");
    await render(true, true);
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("加载失败");
    expect(document.querySelector('[role="status"]')).toBeNull();
    const retry = [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === "重试");
    await act(async () => retry!.click());
    expect(onRequest).toHaveBeenCalledTimes(2);
    await render(false, false, true);
    const item = [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === reference.title);
    await act(async () => item!.click());
    expect(onAdd).toHaveBeenCalledExactlyOnceWith(reference);
  });
});

describe("composer budget entry interaction", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });
  const budgetControl: ChatComposerBudgetControl = {
    sessionId: "session-budget",
    revision: 7,
    maxCallsPerTurn: 32,
    onSave: vi.fn(),
  };
  function baseProps(budget?: ChatComposerBudgetControl, capabilityDisabled = false): ChatComposerPlusMenuProps {
    return {
      lang: "zh", attachmentDisabled: false, sessionReferences: [], mentalModelEnabled: false,
      runtimeStatusEnabled: true, promptSuggestionEnabled: true,
      capabilityDisabled, onMentalModelEnabledChange: vi.fn(),
      onRuntimeStatusEnabledChange: vi.fn(), onPromptSuggestionEnabledChange: vi.fn(),
      budget,
    };
  }
  async function renderMenu(budget?: ChatComposerBudgetControl, capabilityDisabled = false) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root!.render(
      <VuiProvider><ChatComposerPlusMenu {...baseProps(budget, capabilityDisabled)} /></VuiProvider>,
    ));
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="更多操作"]')!.click());
  }
  function budgetEntry(): HTMLButtonElement | undefined {
    return [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')]
      .find((button) => button.textContent?.includes("预算与额度"));
  }
  it("renders no budget entry without the budget control", async () => {
    await renderMenu(undefined);
    expect(budgetEntry()).toBeUndefined();
  });
  it("opens the budget side popover from the capabilities section when the control is present", async () => {
    await renderMenu(budgetControl);
    const entry = budgetEntry();
    expect(entry).toBeDefined();
    expect(entry?.disabled).toBe(false);
    const capabilities = document.body.querySelector('[data-testid="chat-composer-plus-conversation-capabilities"]');
    expect(capabilities?.textContent).toContain("预算与额度");
    await act(async () => entry!.click());
    const panel = document.body.querySelector('[data-testid="chat-composer-budget-popover-body"]');
    expect(panel?.textContent).toContain("预算与额度");
  });
  it("keeps the budget entry disabled while the session capability gate is off", async () => {
    await renderMenu(budgetControl, true);
    expect(budgetEntry()?.disabled).toBe(true);
  });
});

describe("composer private attachment dialog interaction", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });
  async function renderMenu(onAttachSecret?: (input: { value: string; label?: string }) => Promise<void>) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    await act(async () => root!.render(
      <VuiProvider><ChatComposerPlusMenu lang="zh" showCapabilities={false} showReferences={false}
        attachmentDisabled={false} sessionReferences={[]} onAddAttachments={vi.fn()}
        onAttachSecret={onAttachSecret} /></VuiProvider>,
    ));
    await act(async () => container.querySelector<HTMLButtonElement>('button[aria-label="更多操作"]')!.click());
  }
  function secretMenuItem(): HTMLButtonElement | undefined {
    return [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')]
      .find((button) => button.textContent?.includes("隐私附件"));
  }
  function passwordInput(): HTMLInputElement {
    const element = document.querySelector<HTMLInputElement>('input[type="password"]');
    if (!element) throw new Error("missing password input");
    return element;
  }
  function setInputValue(element: HTMLInputElement, value: string) {
    act(() => {
      Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
      element.dispatchEvent(new Event("input", { bubbles: true }));
    });
  }
  it("renders no private attachment menu item without the prop", async () => {
    await renderMenu(undefined);
    expect(secretMenuItem()).toBeUndefined();
    expect(document.body.textContent).not.toContain("隐私附件");
  });
  it("collects the optional label and plaintext once, then drops the value after staging", async () => {
    const onAttachSecret = vi.fn(async () => {});
    await renderMenu(onAttachSecret);
    expect(secretMenuItem()?.disabled).toBe(false);
    await act(async () => secretMenuItem()!.click());
    expect(document.querySelector('input[type="password"]')).not.toBeNull();
    setInputValue(document.querySelector<HTMLInputElement>('input[aria-label="隐私附件显示名"]')!, "中转站密钥");
    setInputValue(passwordInput(), "sk-relay-9f8a-live");
    const submit = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "添加")!;
    await act(async () => submit.click());
    expect(onAttachSecret).toHaveBeenCalledExactlyOnceWith({ value: "sk-relay-9f8a-live", label: "中转站密钥" });
    // Success closes the dialog; the plaintext state was dropped with it.
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.body.textContent).not.toContain("sk-relay-9f8a-live");
  });
  it("keeps the dialog open with the value intact when staging fails, and shows the error", async () => {
    const onAttachSecret = vi.fn(async () => { throw new Error("Launcher 未确认隐私附件暂存。"); });
    await renderMenu(onAttachSecret);
    await act(async () => secretMenuItem()!.click());
    setInputValue(passwordInput(), "sk-retry-input");
    const submit = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "添加")!;
    await act(async () => submit.click());
    expect(document.querySelector('[role="alert"]')?.textContent).toContain("未确认隐私附件暂存");
    // In-memory only, kept for a correction; still absent from any storage.
    expect(passwordInput().value).toBe("sk-retry-input");
    expect(localStorage.length).toBe(0);
    // A correction succeeds and closes the dialog, dropping the value.
    onAttachSecret.mockImplementation(async () => {});
    await act(async () => submit.click());
    expect(onAttachSecret).toHaveBeenCalledTimes(2);
    expect(document.querySelector('input[type="password"]')).toBeNull();
    expect(document.querySelector('[role="alert"]')).toBeNull();
  });
  it("offers only label and value fields, with no kind selector, when the label is omitted", async () => {
    const onAttachSecret = vi.fn(async () => {});
    await renderMenu(onAttachSecret);
    await act(async () => secretMenuItem()!.click());
    // One unified path for any secret content: no type combobox exists in the dialog.
    expect(document.querySelector('[role="combobox"]')).toBeNull();
    expect(document.querySelectorAll('[role="option"]').length).toBe(0);
    setInputValue(passwordInput(), "pw-value");
    const submit = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "添加")!;
    await act(async () => submit.click());
    expect(onAttachSecret).toHaveBeenCalledExactlyOnceWith({ value: "pw-value" });
  });
  it("disables submit while the value is empty", async () => {
    const onAttachSecret = vi.fn(async () => {});
    await renderMenu(onAttachSecret);
    await act(async () => secretMenuItem()!.click());
    const submit = [...document.querySelectorAll<HTMLButtonElement>("button")].find((button) => button.textContent?.trim() === "添加")!;
    expect(submit.disabled).toBe(true);
  });
});

describe("composer secret request banner", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });
  const request = { purpose: "连接中转站需要 API 密钥", label: "中转站密钥" };
  function banner(): Element | null {
    return document.querySelector('[data-testid="chat-composer-secret-request"]');
  }
  function actionButton(label: string): HTMLButtonElement {
    const element = [...container.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.trim() === label);
    if (!element) throw new Error(`missing banner action ${label}`);
    return element;
  }
  async function renderMenu(secretRequestValue: typeof request | null,
    onAttachSecret?: (input: { value: string; label?: string }) => Promise<void>) {
    container = document.createElement("div");
    document.body.append(container);
    root = createRoot(container);
    const onDismiss = vi.fn();
    await act(async () => root!.render(
      <VuiProvider><ChatComposerPlusMenu lang="zh" showCapabilities={false} showReferences={false}
        attachmentDisabled={false} sessionReferences={[]} onAddAttachments={vi.fn()}
        onAttachSecret={onAttachSecret} secretRequest={secretRequestValue}
        onSecretRequestDismiss={onDismiss} /></VuiProvider>,
    ));
    return onDismiss;
  }
  it("renders no banner without a request (null or omitted)", async () => {
    await renderMenu(null);
    expect(banner()).toBeNull();
    expect(document.body.textContent).not.toContain("助理请求隐私内容");
  });
  it("surfaces the request with its purpose and suggested display name", async () => {
    await renderMenu(request);
    const element = banner();
    expect(element).not.toBeNull();
    expect(element!.textContent).toContain("助理请求隐私内容：连接中转站需要 API 密钥");
    expect(element!.textContent).toContain("建议显示名：中转站密钥");
    expect(element!.textContent).toContain("立即附加");
    expect(element!.textContent).toContain("忽略");
  });
  it("opens the private attachment dialog with the suggested label prefilled", async () => {
    const onAttachSecret = vi.fn(async () => {});
    await renderMenu(request, onAttachSecret);
    await act(async () => actionButton("立即附加").click());
    const password = document.querySelector<HTMLInputElement>('input[type="password"]');
    expect(password).not.toBeNull();
    // The suggestion lands in the display-name field, ready to edit or send.
    expect(document.querySelector<HTMLInputElement>('input[aria-label="隐私附件显示名"]')!.value).toBe("中转站密钥");
    // The banner hides while the dialog is open so the two never stack.
    expect(banner()).toBeNull();
    const setInput = (element: HTMLInputElement, value: string) => {
      act(() => {
        Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(element, value);
        element.dispatchEvent(new Event("input", { bubbles: true }));
      });
    };
    setInput(password!, "sk-relay-9f8a-live");
    const submit = [...document.querySelectorAll<HTMLButtonElement>("button")]
      .find((button) => button.textContent?.trim() === "添加")!;
    await act(async () => submit.click());
    expect(onAttachSecret).toHaveBeenCalledExactlyOnceWith({ value: "sk-relay-9f8a-live", label: "中转站密钥" });
  });
  it("reports the dismissal when the operator ignores the request", async () => {
    const onDismiss = await renderMenu(request);
    await act(async () => actionButton("忽略").click());
    expect(onDismiss).toHaveBeenCalledExactlyOnceWith();
    // The banner stays only as long as the host keeps passing the request:
    // dismissal memory is the host's keyed state, not the menu's.
    expect(banner()).not.toBeNull();
  });
});

describe("composer reference context interaction", () => {
  let root: Root | null = null;
  let container: HTMLDivElement;
  afterEach(async () => {
    await act(async () => root?.unmount());
    container?.remove();
    root = null;
  });
  const reference = { referenceId: "session:previous", kind: "session" as const, sessionId: "previous", title: "历史验收", createdAt: "2026-10-13T00:00:00Z" };
  const options = [{ id: "previous", title: "历史验收", reference }];
  async function render(scoped: typeof options | null, fallback = [] as typeof options, paginated = false) {
    container = document.createElement("div"); document.body.append(container);
    root = createRoot(container);
    const onAddSessionReference = vi.fn();
    const props: ChatComposerPlusMenuProps = {
      lang: "zh", attachmentDisabled: false, sessionReferences: fallback, onAddSessionReference,
      mentalModelEnabled: false, runtimeStatusEnabled: true, promptSuggestionEnabled: true,
      capabilityDisabled: false, onMentalModelEnabledChange: vi.fn(),
      onRuntimeStatusEnabledChange: vi.fn(), onPromptSuggestionEnabledChange: vi.fn(),
    };
    function Harness() {
      const [loaded, setLoaded] = useState(false);
      const nextPage = [{ ...options[0], id: "older-31", title: "第31条历史会话", reference: { ...reference, referenceId: "session:older-31", sessionId: "older-31" } }];
      const value = scoped === null ? null : {
        options: loaded ? [...scoped, ...nextPage] : scoped,
        hasMore: paginated && !loaded, onLoadMore: () => setLoaded(true),
      };
      return <VuiProvider><ChatComposerSessionReferencesContext.Provider value={value}><ChatComposerPlusMenu {...props} /></ChatComposerSessionReferencesContext.Provider></VuiProvider>;
    }
    await act(async () => root!.render(<Harness />));
    await act(async () => container.querySelector<HTMLButtonElement>('[aria-label="更多操作"]')!.click());
    return onAddSessionReference;
  }
  it("enables an empty-directory menu using scoped options and submits the native reference", async () => {
    const onAdd = await render(options);
    const action = document.querySelector<HTMLButtonElement>('[data-plus-menu-item="true"][data-action="reference-session"]')
      ?? [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')].find(button => button.textContent?.includes("引用会话"));
    expect(action?.disabled).toBe(false);
    await act(async () => action!.click());
    const candidate = [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === "历史验收");
    expect(candidate).toBeDefined();
    await act(async () => candidate!.click());
    expect(onAdd).toHaveBeenCalledExactlyOnceWith(reference);
  });
  it("keeps normal Chat props when there is no scoped override", async () => {
    await render(null, options);
    const action = [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')].find(button => button.textContent?.includes("引用会话"));
    expect(action?.disabled).toBe(false);
  });
  it("does not fall back to global candidates when the scoped list is empty", async () => {
    await render([], options);
    const action = [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')].find(button => button.textContent?.includes("引用会话"));
    expect(action?.disabled).toBe(true);
  });
  it("loads older candidates in the picker and selects a session beyond the first page", async () => {
    const firstPage = Array.from({ length: 30 }, (_, i) => ({ ...options[0], id: `recent-${i}`, title: `近期 ${i}` }));
    const onAdd = await render(firstPage, [], true);
    const action = [...document.querySelectorAll<HTMLButtonElement>('[data-plus-menu-item="true"]')].find(button => button.textContent?.includes("引用会话"));
    await act(async () => action!.click());
    const more = [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === "更多会话");
    expect(more).toBeDefined();
    await act(async () => more!.click());
    const older = [...document.querySelectorAll<HTMLButtonElement>('button')].find(button => button.textContent === "第31条历史会话");
    expect(older).toBeDefined();
    await act(async () => older!.click());
    expect(onAdd).toHaveBeenCalledExactlyOnceWith(expect.objectContaining({ sessionId: "older-31" }));
  });
});
