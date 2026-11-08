// @vitest-environment happy-dom
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { ConfigCatalogModel } from "../../api/types";
import type { VStringSelectProps } from "../../components/vui/forms/VStringSelect";
import { CONFIG_COPY } from "./configCopy";
import { ConfigModelEntryEditor, type ConfigModelEntryEditorProps } from "./ConfigModelEntryEditor";
import type { ModelFieldEdits } from "./modelEditableFields";

// The VUI select owns its Radix interactions in its own tests. This adapter
// isolates the editor's selection and draft contract from floating UI.
vi.mock("../../components/vui", async (importOriginal) => ({
  ...await importOriginal<Record<string, unknown>>(),
  VStringSelect: ({ ariaLabel, isDisabled, options, value, onValueChange }: VStringSelectProps) => (
    <select aria-label={ariaLabel} disabled={isDisabled} value={value} onChange={(event) => onValueChange(event.target.value)}>
      {options.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
    </select>
  ),
}));

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

function catalogModel(entry: Record<string, unknown> = {}): ConfigCatalogModel {
  return {
    availability: "pinned", label: "Existing", modelKey: "stable-id", modelRef: "local/stable-id",
    status: "pinned", upstreamId: "upstream", capabilities: {}, reasoningEffortValues: ["low", "high"],
    draftEntry: { upstream_id: "upstream", label: "Existing", wire_protocol: "responses", ...entry },
  };
}

let container: HTMLDivElement;
let root: Root;
let props: ConfigModelEntryEditorProps;

async function render(overrides: Partial<ConfigModelEntryEditorProps> = {}) {
  props = { ...props, ...overrides };
  await act(async () => root.render(<ConfigModelEntryEditor {...props} />));
}

function input(field: string) {
  return container.querySelector<HTMLInputElement>(`[data-model-edit-field="${field}"] input`)!;
}

async function type(field: string, value: string) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input(field), value);
    input(field).dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.append(container);
  root = createRoot(container);
  props = {
    model: catalogModel(), disabled: false, busy: false, copy: CONFIG_COPY.zh, edits: {},
    onEditsChange: vi.fn((edits: ModelFieldEdits) => {
      props = { ...props, edits };
      root.render(<ConfigModelEntryEditor {...props} />);
    }),
  };
});

afterEach(async () => {
  await act(async () => root.unmount());
  container.remove();
  vi.clearAllMocks();
});

describe("controlled model entry editor", () => {
  it("keeps identity and context visible, inherits generation parameters and uses only the page save", async () => {
    await render();
    for (const field of ["label", "model", "context_window", "enabled"]) expect(input(field)).not.toBeNull();
    for (const field of ["temperature", "max_output_tokens", "timeout", "streaming", "default_reasoning_effort"]) {
      expect(container.querySelector(`[data-model-edit-field="${field}"]`)).toBeNull();
    }
    expect(container.querySelector('[data-model-action="save-edit"]')).toBeNull();
    expect(container.querySelector('[data-model-edit-pending-save]')).toBeNull();
    expect(container.textContent).not.toContain(CONFIG_COPY.zh.modelEditPendingSave);
    expect(container.querySelector('[data-model-edit-generation-empty]')?.textContent).toBe(CONFIG_COPY.zh.modelEditGenerationEmpty);
    expect(container.querySelector('[data-model-resolved-route]')).toBeNull();
    expect(container.querySelector('[data-model-edit-field="wire_protocol"]')).toBeNull();
    expect(container.textContent).not.toContain(CONFIG_COPY.zh.modelEditGenerationHint);
    expect(container.textContent).not.toContain(CONFIG_COPY.zh.modelEditProtocolNote);
    const heading = container.querySelector("h3")!;
    expect(heading.textContent).toBe(CONFIG_COPY.zh.modelEditGenerationTitle);
    expect(heading.parentElement?.querySelector("select")?.getAttribute("aria-label")).toBe(CONFIG_COPY.zh.modelEditAddParameter);
    expect(props.onEditsChange).not.toHaveBeenCalled();
    await type("label", "Renamed");
    expect(container.querySelector('[data-model-edit-pending-save]')).toBeNull();
  });

  it("adds only the requested override, preserves incomplete and empty numbers, and emits changed whitelist fields", async () => {
    await render();
    const add = container.querySelector<HTMLSelectElement>(`select[aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"]`)!;
    await act(async () => {
      add.value = "temperature";
      add.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(input("temperature").value).toBe("");
    expect(container.querySelector('[data-model-edit-generation-empty]')).toBeNull();
    expect(props.onEditsChange).not.toHaveBeenCalled();
    await type("temperature", "1e");
    expect(input("temperature").value).toBe("1e");
    expect(input("temperature").getAttribute("aria-invalid")).toBe("true");
    expect(props.edits).toEqual({ temperature: "1e" });
    expect(container.querySelector('[role="alert"]')?.textContent).toBe(CONFIG_COPY.zh.saveBlockedInvalid);
    await type("temperature", "0.2");
    await type("label", "Renamed");
    expect(props.edits).toEqual({ temperature: "0.2", label: "Renamed" });
    await type("label", "Existing");
    expect(props.edits).toEqual({ temperature: "0.2" });
    await type("temperature", "");
    expect(props.edits).toEqual({});
    expect(input("temperature").value).toBe("");
  });

  it("restores controlled page drafts after selection changes and keeps clear operations pending", async () => {
    const first = catalogModel({ defaults: { timeout: 60, default_reasoning_effort: "custom" } });
    await render({ model: first, edits: { timeout: "" } });
    expect(input("timeout").value).toBe("");
    const reasoning = container.querySelector<HTMLSelectElement>(`select[aria-label="${CONFIG_COPY.zh.modelEditFieldReasoningEffort}"]`)!;
    expect([...reasoning.options].map((option) => option.value)).toEqual(["", "low", "high", "custom"]);
    await render({ model: { ...catalogModel(), modelRef: "local/other", modelKey: "other" }, edits: { label: "Other draft" } });
    expect(input("label").value).toBe("Other draft");
    expect(input("timeout")).toBeNull();
    await render({ model: first, edits: { timeout: "" } });
    expect(input("timeout").value).toBe("");
    expect(input("label").value).toBe("Existing");
  });

  it("retains compatibility save callbacks while preventing invalid and busy saves", async () => {
    const save = vi.fn();
    await render({ onSave: save, edits: { context_window: "262144" } });
    const saveButton = () => container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')!;
    await act(async () => saveButton().click());
    expect(save).toHaveBeenCalledWith("stable-id", { context_window: "262144" });
    await render({ edits: { context_window: "invalid" } });
    expect(saveButton().disabled).toBe(true);
    await render({ busy: true, edits: { label: "Updated" } });
    expect(saveButton().disabled).toBe(true);
    expect(input("label").disabled).toBe(true);
    expect(input("enabled").disabled).toBe(true);
    expect(container.querySelector<HTMLSelectElement>("select")?.disabled).toBe(true);
  });

  it("shows stored defaults without changing unknown or protocol fields and saves only explicit whitelist edits", async () => {
    const model = catalogModel({
      context_window: 200000,
      enabled: false,
      custom_entry: { future: "preserve" },
      interaction_contract: "tool-loop",
      defaults: {
        temperature: 0, max_output_tokens: 4096, timeout: 30, streaming: false,
        default_reasoning_effort: "custom", unknown_parameter: { nested: true },
      },
    });
    const original = structuredClone(model);
    const save = vi.fn();
    await render({ model, onSave: save });
    expect(input("temperature").value).toBe("0");
    expect(input("max_output_tokens").value).toBe("4096");
    expect(input("timeout").value).toBe("30");
    expect(input("streaming").checked).toBe(false);
    expect(input("enabled").checked).toBe(false);
    expect(container.querySelector<HTMLSelectElement>(`select[aria-label="${CONFIG_COPY.zh.modelEditFieldReasoningEffort}"]`)?.value).toBe("custom");
    expect(container.querySelector(`select[aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"]`)).toBeNull();
    expect(container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')?.disabled).toBe(true);
    expect(props.onEditsChange).not.toHaveBeenCalled();
    await type("label", "Renamed");
    expect(props.edits).toEqual({ label: "Renamed" });
    await act(async () => container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')!.click());
    expect(save).toHaveBeenCalledWith("stable-id", { label: "Renamed" });
    expect(model).toEqual(original);
  });

  it("expands a parameter without creating a save and locks all controls when disabled", async () => {
    const save = vi.fn();
    await render({ onSave: save });
    const add = container.querySelector<HTMLSelectElement>(`select[aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"]`)!;
    await act(async () => {
      add.value = "streaming";
      add.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(input("streaming").checked).toBe(true);
    expect(props.onEditsChange).not.toHaveBeenCalled();
    expect(container.querySelector<HTMLButtonElement>('[data-model-action="save-edit"]')?.disabled).toBe(true);
    expect(save).not.toHaveBeenCalled();
    await render({ disabled: true });
    expect([...container.querySelectorAll<HTMLInputElement | HTMLSelectElement>("input, select")].every((control) => control.disabled)).toBe(true);
  });
});
