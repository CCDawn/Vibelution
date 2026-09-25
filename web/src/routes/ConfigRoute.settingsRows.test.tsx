// @vitest-environment happy-dom
/**
 * Settings-align wave 1 — ConfigSectionEditor row integration tests:
 * - view-mode immediate fields (boolean/select) host live controls wired to
 *   onImmediateFieldChange with row status badges;
 * - edit-mode json/number/list controls hard-validate and invalid drafts block
 *   the section save (onSaveSection must not fire);
 * - number stepper clamps to schema bounds; list errors carry line numbers.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { CONFIG_COPY, ConfigSectionEditor, defaultSectionUiState, type ConfigSectionUiState } from "./ConfigRoute";
import type { ConfigEditorMeta, ConfigEditorSection } from "../api/types";

const SECTION: ConfigEditorSection = {
  id: "context-compression",
  path: "context_compression",
  title: "上下文压缩",
  summary: "",
  fieldCount: 7,
};

const COMMITTED_VALUE = {
  enabled: true,
  compression_model: "qwen-turbo",
  max_token_limit: 16000,
  summary_chars: { light: 500 },
  micro_compact_tool_whitelist: ["read_file_tool"],
};

function meta(path: string, kind: ConfigEditorMeta["kind"], extra: Partial<ConfigEditorMeta> = {}): ConfigEditorMeta {
  return { path, label: path, hint: "", kind, badge: "", options: [], ...extra };
}

const META_MAP: Record<string, ConfigEditorMeta> = {
  context_compression: meta("context_compression", "object"),
  "context_compression.enabled": meta("context_compression.enabled", "boolean"),
  "context_compression.compression_model": meta("context_compression.compression_model", "select", {
    options: [{ value: "qwen-turbo", label: "qwen-turbo" }],
  }),
  "context_compression.max_token_limit": meta("context_compression.max_token_limit", "number", {
    minimum: 1000,
    maximum: 200000,
    unit: "令牌",
  }),
  "context_compression.summary_chars": meta("context_compression.summary_chars", "json"),
  "context_compression.micro_compact_tool_whitelist": meta("context_compression.micro_compact_tool_whitelist", "string_list"),
};

type RenderHarness = {
  container: HTMLElement;
  root: Root;
  onImmediateFieldChange: ReturnType<typeof vi.fn>;
  onUiStateChange: ReturnType<typeof vi.fn>;
  onSaveSection: ReturnType<typeof vi.fn>;
  rerender: (uiState: ConfigSectionUiState) => Promise<void>;
};

async function renderEditor(uiState: Partial<ConfigSectionUiState> = {}, value: unknown = COMMITTED_VALUE): Promise<RenderHarness> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onImmediateFieldChange = vi.fn();
  const onSaveSection = vi.fn().mockResolvedValue(true);
  let currentState: ConfigSectionUiState = { ...defaultSectionUiState(SECTION.id), expanded: true, ...uiState };
  // 有状态 harness：onUiStateChange 后用新状态重渲染，模拟真实路由的 setState。
  const onUiStateChange = vi.fn((_sectionId: string, nextState: ConfigSectionUiState) => {
    currentState = nextState;
    render(nextState);
  });

  function render(state: ConfigSectionUiState) {
    act(() => {
      root.render(
        <ConfigSectionEditor
          section={SECTION}
          value={value}
          metaMap={META_MAP}
          lang="zh"
          copy={CONFIG_COPY.zh}
          disabled={false}
          uiState={state}
          onUiStateChange={onUiStateChange}
          onSaveSection={onSaveSection}
          onImmediateFieldChange={onImmediateFieldChange}
          immediateFieldStatus={{}}
          onAvatarImageUpload={vi.fn()}
          onThemeBackgroundImageUpload={vi.fn()}
        />,
      );
    });
  }
  render(currentState);
  return {
    container,
    root,
    onImmediateFieldChange,
    onUiStateChange,
    onSaveSection,
    async rerender(nextState: ConfigSectionUiState) {
      currentState = nextState;
      render(nextState);
    },
  };
}

async function cleanup(harness: RenderHarness) {
  await act(async () => harness.root.unmount());
  harness.container.remove();
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement, nextValue: string) {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(element, nextValue);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function findButtonByText(container: HTMLElement, text: string): HTMLButtonElement | null {
  const buttons = Array.from(container.querySelectorAll("button"));
  return buttons.find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

describe("ConfigSectionEditor settings rows (wave 1)", () => {
  it("hosts a live boolean control in the view row and routes changes through onImmediateFieldChange", async () => {
    const harness = await renderEditor();
    try {
      const row = harness.container.querySelector('[data-testid="row-context_compression.enabled"]');
      expect(row).not.toBeNull();
      expect(row?.getAttribute("data-vui")).toBe("settings-row");
      const checkbox = row?.querySelector('input[type="checkbox"]');
      expect(checkbox).not.toBeNull();
      await act(async () => {
        (checkbox as HTMLInputElement).click();
      });
      expect(harness.onImmediateFieldChange).toHaveBeenCalledWith("context_compression.enabled", false);
      // view 行仍渲染只读值（select/number 等非即时字段）
      expect(harness.container.querySelector('[data-testid="value-context_compression.max_token_limit"]')?.textContent).toContain("16000");
    } finally {
      await cleanup(harness);
    }
  });

  it("keeps a pending-save badge for edited draft rows in edit mode", async () => {
    const draftValue = { ...COMMITTED_VALUE, max_token_limit: "24000" };
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue });
    try {
      const badge = harness.container.querySelector('[data-testid="row-status-context_compression.max_token_limit"]');
      expect(badge?.textContent).toContain(CONFIG_COPY.zh.rowStatusPending);
      expect(badge?.getAttribute("data-vui-row-status")).toBe("pending");
    } finally {
      await cleanup(harness);
    }
  });

  it("renders an inline error for invalid json and blocks the section save", async () => {
    const draftValue = { ...COMMITTED_VALUE, summary_chars: '{\n  "light": 500,\n}' };
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue });
    try {
      expect(harness.container.querySelector('[data-vui-json="invalid"]')).not.toBeNull();
      expect(harness.container.querySelector('[data-vui-json="valid"]')).toBeNull();

      const saveButton = findButtonByText(harness.container, CONFIG_COPY.zh.saveSection);
      expect(saveButton?.getAttribute("title")).toBe(CONFIG_COPY.zh.saveBlockedInvalid);
      await act(async () => {
        saveButton?.click();
      });
      expect(harness.onSaveSection).not.toHaveBeenCalled();
    } finally {
      await cleanup(harness);
    }
  });

  it("shows the weak valid hint for valid json and parses drafts before saving", async () => {
    const draftValue = { ...COMMITTED_VALUE, summary_chars: '{"light": 900}' };
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue });
    try {
      expect(harness.container.querySelector('[data-vui-json="valid"]')).not.toBeNull();
      const saveButton = findButtonByText(harness.container, CONFIG_COPY.zh.saveSection);
      await act(async () => {
        saveButton?.click();
      });
      expect(harness.onSaveSection).toHaveBeenCalledWith("context_compression", {
        ...COMMITTED_VALUE,
        summary_chars: { light: 900 },
      });
    } finally {
      await cleanup(harness);
    }
  });

  it("steps the number within schema bounds and flags out-of-range text", async () => {
    const harness = await renderEditor({ editing: true, advancedExpanded: true });
    try {
      const row = harness.container.querySelector('[data-testid="row-context_compression.max_token_limit"]');
      const stepUp = row?.querySelector('[data-testid="step-up-context_compression.max_token_limit"]');
      await act(async () => {
        (stepUp as HTMLButtonElement).click();
      });
      expect(harness.onUiStateChange).toHaveBeenCalledTimes(1);
      const nextState = harness.onUiStateChange.mock.calls[0]?.[1] as ConfigSectionUiState;
      const stepped = (nextState.draftValue as Record<string, unknown>).max_token_limit;
      expect(Number(stepped)).toBe(16001);

      // 非法文本：步进禁用 + 行内错误
      const numberInput = row?.querySelector("input") as HTMLInputElement | null;
      expect(numberInput).not.toBeNull();
      await act(async () => {
        setInputValue(numberInput as HTMLInputElement, "500");
      });
      expect(harness.container.querySelector('[data-testid="number-error-context_compression.max_token_limit"]')?.textContent).toContain("1000");
    } finally {
      await cleanup(harness);
    }
  });

  it("reports tool-name list errors with line numbers and blocks save", async () => {
    const draftValue = {
      ...COMMITTED_VALUE,
      micro_compact_tool_whitelist: "read_file_tool\nBad Tool!\nread_file_tool",
    };
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue });
    try {
      const errors = harness.container.querySelector('[data-testid="list-errors-context_compression.micro_compact_tool_whitelist"]');
      expect(errors?.textContent).toContain("2");
      expect(errors?.textContent).toContain("3");
      const saveButton = findButtonByText(harness.container, CONFIG_COPY.zh.saveSection);
      await act(async () => {
        saveButton?.click();
      });
      expect(harness.onSaveSection).not.toHaveBeenCalled();
    } finally {
      await cleanup(harness);
    }
  });
});
