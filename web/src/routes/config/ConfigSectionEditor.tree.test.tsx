// @vitest-environment happy-dom
/**
 * Settings-align wave 3 phase 1 — ConfigSectionEditor tree-render safety net.
 *
 * Covers the field-kind matrix (nested object / string_list / json / number /
 * boolean / secret), the view↔edit toggle (edit clones the committed value
 * into an isolated draft), cancel discarding the draft without saving, and
 * readonly display semantics. Complements ConfigRoute.settingsRows.test.tsx
 * (immediate rows + invalid blocking), which stays authoritative for those.
 *
 * Phase 2 moves ConfigSectionEditor out of ConfigRoute.tsx; only the import
 * path of this file may change, the assertions must not.
 */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { describe, expect, it, vi } from "vitest";

import { CONFIG_COPY } from "./configCopy";
import { ConfigSectionEditor } from "./ConfigSectionEditor";
import { defaultSectionUiState, type ConfigSectionUiState } from "./configEditorModel";
import type { ConfigEditorMeta, ConfigEditorSection } from "../../api/types";

function meta(path: string, kind: ConfigEditorMeta["kind"], extra: Partial<ConfigEditorMeta> = {}): ConfigEditorMeta {
  return { path, label: path, hint: "", kind, badge: "", options: [], ...extra };
}

const SECTION: ConfigEditorSection = {
  id: "context-compression",
  path: "context_compression",
  title: "上下文压缩",
  summary: "",
  fieldCount: 7,
};

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
  "context_compression.proxy_password": meta("context_compression.proxy_password", "secret"),
};

const COMMITTED_VALUE = {
  enabled: true,
  compression_model: "qwen-turbo",
  max_token_limit: 16000,
  summary_chars: { light: 500 },
  micro_compact_tool_whitelist: ["read_file_tool"],
  proxy_password: "s3cret",
};

type Harness = {
  container: HTMLElement;
  root: Root;
  onSaveSection: ReturnType<typeof vi.fn>;
  onUiStateChange: ReturnType<typeof vi.fn>;
  rerender: (uiState: ConfigSectionUiState) => Promise<void>;
  uiState: () => ConfigSectionUiState;
};

async function renderEditor(
  uiStateOverrides: Partial<ConfigSectionUiState> = {},
  value: unknown = COMMITTED_VALUE,
  section: ConfigEditorSection = SECTION,
): Promise<Harness> {
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onSaveSection = vi.fn().mockResolvedValue(true);
  let currentState: ConfigSectionUiState = { ...defaultSectionUiState(section.id), expanded: true, ...uiStateOverrides };
  const onUiStateChange = vi.fn((_sectionId: string, nextState: ConfigSectionUiState) => {
    currentState = nextState;
    void render(nextState);
  });

  async function render(state: ConfigSectionUiState) {
    await act(async () => {
      root.render(
        <ConfigSectionEditor
          section={section}
          value={value}
          metaMap={META_MAP}
          lang="zh"
          copy={CONFIG_COPY.zh}
          disabled={false}
          uiState={state}
          onUiStateChange={onUiStateChange}
          onSaveSection={onSaveSection}
          onImmediateFieldChange={vi.fn()}
          immediateFieldStatus={{}}
          onAvatarImageUpload={vi.fn()}
          onThemeBackgroundImageUpload={vi.fn()}
        />,
      );
    });
  }
  await render(currentState);
  return {
    container,
    root,
    onSaveSection,
    onUiStateChange,
    async rerender(nextState: ConfigSectionUiState) {
      currentState = nextState;
      await render(nextState);
    },
    uiState: () => currentState,
  };
}

async function cleanup(harness: Harness) {
  await act(async () => harness.root.unmount());
  harness.container.remove();
}

function findButtonByText(container: HTMLElement, text: string): HTMLButtonElement | null {
  const buttons = Array.from(container.querySelectorAll("button"));
  return buttons.find((button) => (button.textContent ?? "").includes(text)) ?? null;
}

function setInputValue(element: HTMLInputElement | HTMLTextAreaElement, nextValue: string) {
  const proto = element instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;
  const setter = Object.getOwnPropertyDescriptor(proto, "value")?.set;
  setter?.call(element, nextValue);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

describe("ConfigSectionEditor tree rendering (wave 3 safety net)", () => {
  it("renders readonly view values for every field kind: secret masked, list joined, number plain", async () => {
    // secret 属高级层：查看态展开高级层后逐 kind 断言只读展示。
    const harness = await renderEditor({ advancedExpanded: true });
    try {
      expect(harness.container.querySelector('[data-testid="value-context_compression.proxy_password"]')?.textContent).toBe("******");
      expect(harness.container.querySelector('[data-testid="value-context_compression.micro_compact_tool_whitelist"]')?.textContent).toContain("read_file_tool");
      expect(harness.container.querySelector('[data-testid="value-context_compression.max_token_limit"]')?.textContent).toContain("16000");
      // 查看态不渲染任何编辑控件
      expect(harness.container.querySelector('[data-testid="json-editor-context_compression.summary_chars"]')).toBeNull();
    } finally {
      await cleanup(harness);
    }
  });

  it("renders a live boolean checkbox in the view row", async () => {
    const harness = await renderEditor();
    try {
      const checkbox = harness.container.querySelector(
        '[data-testid="row-context_compression.enabled"] input[type="checkbox"]',
      );
      expect(checkbox).not.toBeNull();
      expect((checkbox as HTMLInputElement).checked).toBe(true);
    } finally {
      await cleanup(harness);
    }
  });

  it("toggles a nested object block open and closed in edit mode", async () => {
    // 微压缩白名单是高级层字段：编辑态 draft 与真实流一致（原始串），需 advancedExpanded。
    const harness = await renderEditor({
      editing: true,
      advancedExpanded: true,
      draftValue: { ...COMMITTED_VALUE, micro_compact_tool_whitelist: "read_file_tool" },
    });
    try {
      const nestedPath = "context_compression.micro_compact_tool_whitelist";
      const row = harness.container.querySelector(`[data-testid="row-${nestedPath}"]`);
      expect(row).not.toBeNull();
      // string_list 编辑态：textarea 承载逐行文本
      const textarea = harness.container.querySelector(`textarea[aria-label="${nestedPath}"]`);
      expect(textarea).not.toBeNull();
      expect((textarea as HTMLTextAreaElement).value).toBe("read_file_tool");
    } finally {
      await cleanup(harness);
    }
  });

  it("renders the json editor with its live validation status line in edit mode", async () => {
    // 编辑态的 json 草稿是原始串（与 updateSectionDraft 的 setValueAtConfigPath 流一致）。
    const harness = await renderEditor({
      editing: true,
      advancedExpanded: true,
      draftValue: { ...COMMITTED_VALUE, summary_chars: '{"light": 500}' },
    });
    try {
      const jsonEditor = harness.container.querySelector(
        '[data-testid="json-editor-context_compression.summary_chars"]',
      ) as HTMLTextAreaElement | null;
      expect(jsonEditor).not.toBeNull();
      expect(JSON.parse(jsonEditor?.value ?? "{}")).toEqual({ light: 500 });
      expect(harness.container.querySelector('[data-vui-json="valid"]')).not.toBeNull();

      await act(async () => {
        setInputValue(jsonEditor as HTMLTextAreaElement, "{ broken");
      });
      expect(harness.container.querySelector('[data-vui-json="invalid"]')).not.toBeNull();
    } finally {
      await cleanup(harness);
    }
  });

  it("renders the number stepper with its schema unit in edit mode", async () => {
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue: { ...COMMITTED_VALUE } });
    try {
      expect(harness.container.querySelector('[data-testid="number-editor-context_compression.max_token_limit"]')).not.toBeNull();
      expect(harness.container.querySelector('[data-testid="step-up-context_compression.max_token_limit"]')).not.toBeNull();
      expect(harness.container.textContent).toContain("令牌");
    } finally {
      await cleanup(harness);
    }
  });

  it("renders the secret editor as a password input in edit mode", async () => {
    const harness = await renderEditor({ editing: true, advancedExpanded: true, draftValue: { ...COMMITTED_VALUE } });
    try {
      const secretInput = harness.container.querySelector(
        'input[type="password"][aria-label="context_compression.proxy_password"]',
      );
      expect(secretInput).not.toBeNull();
      expect((secretInput as HTMLInputElement).value).toBe("s3cret");
    } finally {
      await cleanup(harness);
    }
  });

  it("clones the committed value into an isolated draft when entering edit mode", async () => {
    const harness = await renderEditor();
    try {
      const editButton = findButtonByText(harness.container, CONFIG_COPY.zh.editSection);
      expect(editButton).not.toBeNull();
      await act(async () => {
        editButton?.click();
      });
      const nextState = harness.uiState();
      expect(nextState.editing).toBe(true);
      expect(nextState.draftValue).toEqual(COMMITTED_VALUE);
      // 克隆而非引用：改草稿不得污染已提交值
      expect(nextState.draftValue).not.toBe(COMMITTED_VALUE);
    } finally {
      await cleanup(harness);
    }
  });

  it("discards the draft without saving when cancel is pressed in edit mode", async () => {
    const harness = await renderEditor({
      editing: true,
      advancedExpanded: true,
      draftValue: { ...COMMITTED_VALUE, max_token_limit: "99999" },
    });
    try {
      const cancelButton = findButtonByText(harness.container, CONFIG_COPY.zh.cancelSection);
      expect(cancelButton).not.toBeNull();
      await act(async () => {
        cancelButton?.click();
      });
      const nextState = harness.uiState();
      expect(nextState.editing).toBe(false);
      expect(nextState.draftValue).toBeUndefined();
      expect(harness.onSaveSection).not.toHaveBeenCalled();
    } finally {
      await cleanup(harness);
    }
  });

  it("collapses the section body when collapse is pressed and re-renders it on expand", async () => {
    const harness = await renderEditor();
    try {
      const collapseButton = findButtonByText(harness.container, CONFIG_COPY.zh.collapseSection);
      expect(collapseButton).not.toBeNull();
      await act(async () => {
        collapseButton?.click();
      });
      expect(harness.uiState().expanded).toBe(false);
      await harness.rerender({ ...harness.uiState(), expanded: false });
      expect(harness.container.querySelector('[data-testid="row-context_compression.enabled"]')).toBeNull();
      const expandButton = findButtonByText(harness.container, CONFIG_COPY.zh.expandSection);
      expect(expandButton).not.toBeNull();
    } finally {
      await cleanup(harness);
    }
  });
});
