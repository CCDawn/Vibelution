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
    expect(container.textContent).toContain(CONFIG_COPY.zh.modelEditPendingSave);
    expect(container.querySelector('[data-model-resolved-route="responses"]')).not.toBeNull();
    expect(container.querySelector('[data-model-edit-field="wire_protocol"]')).toBeNull();
    expect(props.onEditsChange).not.toHaveBeenCalled();
  });

  it("adds only the requested override, preserves incomplete and empty numbers, and emits changed whitelist fields", async () => {
    await render();
    const add = container.querySelector<HTMLSelectElement>(`select[aria-label="${CONFIG_COPY.zh.modelEditAddParameter}"]`)!;
    await act(async () => {
      add.value = "temperature";
      add.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(input("temperature").value).toBe("");
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
  });
});
