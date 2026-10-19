/** @vitest-environment happy-dom */
import React, { act, useState } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";
import { VuiProvider } from "../../components/vui";
import { ChatComposerPlusMenu, ChatComposerSessionReferencesContext, type ChatComposerPlusMenuProps } from "./ChatComposerPlusMenu";
import type { ChatComposerBudgetControl } from "./ChatComposerBudgetPopover";

import source from "./ChatComposerPlusMenu.tsx?raw";
import stylesSource from "./ChatComposerPlusMenu.styles.ts?raw";

describe("ChatComposerPlusMenu contract", () => {
  it("renders one compact vertical menu with grouped sections", () => {
    expect(stylesSource).toContain('popoverContent: "vui-routes-chatcomposerplusmenu popoverContent !w-80');
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
});

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
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
