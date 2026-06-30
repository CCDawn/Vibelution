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
  VTextarea,
} from "./index";
import { VibelutionHeroProvider } from "./renderers/heroui/HeroProvider";

describe("VUI form primitives", () => {
  it("renders dense form controls through the VUI boundary", () => {
    const markup = renderToStaticMarkup(
      <VibelutionHeroProvider>
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
          <VCheckbox isSelected>Running only</VCheckbox>
        </form>
      </VibelutionHeroProvider>,
    );

    expect(markup).toContain('data-vui="field-row"');
    expect(markup).toContain('data-vui="field-tooltip"');
    expect(markup).toContain('data-vui="input"');
    expect(markup).toContain('data-vui="native-input"');
    expect(markup).toContain('data-vui="native-select"');
    expect(markup).toContain('data-vui="native-textarea"');
    expect(markup).toContain('data-vui="select"');
    expect(markup).toContain('data-vui="textarea"');
    expect(markup).toContain('data-vui="checkbox"');
    expect(markup).toContain("MiMo V2.5");
    expect(markup).toContain("Running only");
  });
});
