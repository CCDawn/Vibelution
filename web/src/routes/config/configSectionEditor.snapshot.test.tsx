// @vitest-environment happy-dom
/**
 * Settings-align wave 3 phase 1 — pre-refactor render baselines.
 *
 * Serializes ConfigSectionEditor's rendered DOM (structure/aria, not pixels)
 * for three representative sections (ui / log / context-compression) in view
 * and edit modes into committed vitest snapshots. Phase 2 moves the component
 * out of ConfigRoute.tsx; these snapshots must stay byte-identical afterwards
 * (only import paths may differ). React useId markers are normalized so the
 * baseline survives module moves.
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

const UI_SECTION: ConfigEditorSection = { id: "ui", path: "ui", title: "界面外观", summary: "", fieldCount: 6 };
const UI_VALUE = {
  language: "zh",
  refresh_rate: 5,
  show_ascii_art: true,
  show_welcome: true,
  max_log_entries: 1000,
  workbench_theme: {
    background_image_path: "",
    background_readability: "standard",
  },
};
const UI_META: Record<string, ConfigEditorMeta> = {
  ui: meta("ui", "object"),
  "ui.language": meta("ui.language", "select", { options: [{ value: "zh", label: "中文" }, { value: "en", label: "English" }] }),
  "ui.refresh_rate": meta("ui.refresh_rate", "number", { unit: "秒" }),
  "ui.show_ascii_art": meta("ui.show_ascii_art", "boolean"),
  "ui.show_welcome": meta("ui.show_welcome", "boolean"),
  "ui.max_log_entries": meta("ui.max_log_entries", "number"),
  "ui.workbench_theme": meta("ui.workbench_theme", "background_image"),
  "ui.workbench_theme.background_image_path": meta("ui.workbench_theme.background_image_path", "background_image", {
    options: [{ value: "theme_backgrounds/default.png", label: "默认" }],
  }),
  "ui.workbench_theme.background_readability": meta("ui.workbench_theme.background_readability", "select", {
    options: [{ value: "soft", label: "柔和" }, { value: "standard", label: "标准" }, { value: "strong", label: "增强" }],
  }),
};

const LOG_SECTION: ConfigEditorSection = { id: "log", path: "log", title: "日志记录", summary: "", fieldCount: 6 };
const LOG_VALUE = {
  level: "INFO",
  file_enabled: true,
  file_path: "logs/app.log",
  detailed_traceback: true,
  third_party: {
    httpx: "WARNING",
    openai: "WARNING",
  },
};
const LOG_META: Record<string, ConfigEditorMeta> = {
  log: meta("log", "object"),
  "log.level": meta("log.level", "select", { options: [{ value: "INFO", label: "INFO" }, { value: "DEBUG", label: "DEBUG" }] }),
  "log.file_enabled": meta("log.file_enabled", "boolean"),
  "log.file_path": meta("log.file_path", "path"),
  "log.detailed_traceback": meta("log.detailed_traceback", "boolean"),
  "log.third_party": meta("log.third_party", "object"),
  "log.third_party.httpx": meta("log.third_party.httpx", "select", { options: [{ value: "WARNING", label: "WARNING" }, { value: "INFO", label: "INFO" }] }),
  "log.third_party.openai": meta("log.third_party.openai", "select", { options: [{ value: "WARNING", label: "WARNING" }] }),
};

const CC_SECTION: ConfigEditorSection = {
  id: "context-compression",
  path: "context_compression",
  title: "上下文压缩",
  summary: "",
  fieldCount: 7,
};
const CC_VALUE = {
  enabled: true,
  compression_model: "qwen-turbo",
  max_token_limit: 16000,
  summary_chars: { light: 500 },
  micro_compact_tool_whitelist: ["read_file_tool"],
};
const CC_META: Record<string, ConfigEditorMeta> = {
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

/** 序列化渲染输出并抹平 React useId 等环境差异，保证基线只承载结构。 */
function serialize(root: Root, container: HTMLElement, uiState: ConfigSectionUiState, value: unknown, section: ConfigEditorSection, metaMap: Record<string, ConfigEditorMeta>): string {
  let html = "";
  void root; // root kept alive by caller
  const element = (
    <ConfigSectionEditor
      section={section}
      value={value}
      metaMap={metaMap}
      lang="zh"
      copy={CONFIG_COPY.zh}
      disabled={false}
      uiState={uiState}
      onUiStateChange={vi.fn()}
      onSaveSection={vi.fn().mockResolvedValue(true)}
      onImmediateFieldChange={vi.fn()}
      immediateFieldStatus={{}}
      onAvatarImageUpload={vi.fn()}
      onThemeBackgroundImageUpload={vi.fn()}
    />
  );
  act(() => {
    root.render(element);
  });
  html = container.innerHTML;
  return html
    .replace(/«r[0-9]+»/g, "#id")
    .replace(/<!--.*?-->/g, "");
}

function baseState(sectionId: string, overrides: Partial<ConfigSectionUiState> = {}): ConfigSectionUiState {
  return { ...defaultSectionUiState(sectionId), expanded: true, ...overrides };
}

describe("ConfigSectionEditor render baselines (wave 3 pre-refactor)", () => {
  let container: HTMLElement;
  let root: Root;

  function renderCase(name: string, section: ConfigEditorSection, value: unknown, metaMap: Record<string, ConfigEditorMeta>, uiState: ConfigSectionUiState) {
    it(name, () => {
      act(() => {
        container = document.createElement("div");
        document.body.appendChild(container);
        root = createRoot(container);
      });
      try {
        const html = serialize(root, container, uiState, value, section, metaMap);
        expect(html).toMatchSnapshot();
      } finally {
        act(() => {
          root.unmount();
        });
        container.remove();
      }
    });
  }

  renderCase("ui section: view mode with background theme card", UI_SECTION, UI_VALUE, UI_META, baseState("ui"));
  renderCase(
    "ui section: edit mode with expanded theme object",
    UI_SECTION,
    UI_VALUE,
    UI_META,
    { ...baseState("ui", { editing: true, draftValue: JSON.parse(JSON.stringify(UI_VALUE)) }), expandedPaths: { "ui.workbench_theme": true } },
  );
  renderCase("log section: view mode with nested third_party group", LOG_SECTION, LOG_VALUE, LOG_META, baseState("log"));
  renderCase("context-compression section: view mode", CC_SECTION, CC_VALUE, CC_META, baseState("context-compression"));
  renderCase(
    "context-compression section: edit mode with raw-text drafts",
    CC_SECTION,
    CC_VALUE,
    CC_META,
    baseState("context-compression", {
      editing: true,
      advancedExpanded: true,
      draftValue: {
        ...CC_VALUE,
        summary_chars: '{"light": 500}',
        micro_compact_tool_whitelist: "read_file_tool",
      },
    }),
  );
});
