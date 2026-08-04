import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import {
  VCheckbox,
  VFieldRow,
  VInput,
  VNativeInput,
  VNativeSelect,
  VNativeTextarea,
  VSelect,
  VStringSelect,
  VTabs,
  VTextarea,
} from "./index";
import { VuiProvider } from "./VuiProvider";

describe("VUI form primitives", () => {
  it("renders dense form controls through the VUI boundary", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <form data-test-id="vui-form">
          <VFieldRow label="Model" tooltip="Choose the model bound to this task">
            <VSelect
              aria-label="Model"
              defaultSelectedKey="mimo"
              options={[
                { id: "mimo", label: "MiMo V2.5" },
                { id: "qwen", label: "Qwen3" },
              ]}
            />
          </VFieldRow>
          <VInput aria-label="Filter sessions" placeholder="Filter sessions" />
          <VTextarea aria-label="Notes" placeholder="Add notes" minRows={3} />
          <VNativeInput aria-label="Native title" value="Title" readOnly />
          <VNativeSelect aria-label="Native status" value="ready" onChange={() => undefined}>
            <option value="ready">Ready</option>
          </VNativeSelect>
          <VNativeTextarea aria-label="Native notes" value="Notes" readOnly minRows={2} />
          <VCheckbox isSelected density="normal">Running only</VCheckbox>
        </form>
      </VuiProvider>,
    );

    expect(markup).toContain('data-vui="field-row"');
    expect(markup).toContain('data-vui="field-tooltip"');
    expect(markup).toContain('data-vui="input"');
    expect(markup).toContain('data-vui="native-input"');
    expect(markup).toContain('data-vui="native-select"');
    expect(markup).toContain('data-vui="native-textarea"');
    expect(markup).toContain('data-vui="select"');
    expect(markup).toContain('data-renderer="radix"');
    expect(markup).toContain('data-vui="textarea"');
    expect(markup).toContain('data-vui="checkbox"');
    expect(markup).toContain('data-density="compact"');
    expect(markup).toContain('data-density="normal"');
    expect(markup).toContain("h-[var(--vui-control-height-sm)]");
    expect(markup).toContain("min-h-[var(--vui-control-height-md)]");
    expect(markup).toContain('data-slot="checkbox-content"');
    expect(markup).toContain('data-slot="checkbox-control"');
    expect(markup).toContain('data-slot="checkbox-indicator"');
    expect(markup).toContain('type="checkbox"');
    expect(markup).toContain("MiMo V2.5");
    expect(markup).toContain("Running only");
  });

  it("exports Radix tabs list chrome", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <VTabs
          aria-label="Sections"
          defaultValue="a"
          items={[
            { id: "a", label: "Basics", content: <p>A</p> },
            { id: "b", label: "Ops", content: <p>B</p> },
          ]}
        />
      </VuiProvider>,
    );
    expect(markup).toContain('data-vui="tabs"');
    expect(markup).toContain('data-slot="tabs-list"');
    expect(markup).toContain("Basics");
    expect(markup).toContain("Ops");
  });

  it("string select routes through Radix VSelect portal", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <VStringSelect
          ariaLabel="Mode"
          value="a"
          onValueChange={() => undefined}
          options={[
            { value: "a", label: "Alpha" },
            { value: "b", label: "Beta" },
          ]}
        />
      </VuiProvider>,
    );
    expect(markup).toContain('data-vui="select"');
    expect(markup).toContain('data-renderer="radix"');
    expect(markup).toContain("Alpha");
  });
});
