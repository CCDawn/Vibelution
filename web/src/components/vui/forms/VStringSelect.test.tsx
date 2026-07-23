import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import { VStringSelect, resolveStringSelectChange } from "./VStringSelect";
import { VuiProvider } from "../VuiProvider";

const options = [
  { value: "safe", label: "Safe" },
  { value: "disabled", label: "Disabled", disabled: true },
];

const optionsWithManualEntry = [
  { value: "", label: "Manual" },
  { value: "safe", label: "Safe" },
];

describe("resolveStringSelectChange", () => {
  it("returns an enabled selection", () => {
    expect(resolveStringSelectChange("safe", options)).toBe("safe");
  });

  it("keeps a cleared selection distinct from a declared empty option", () => {
    expect(resolveStringSelectChange(null, optionsWithManualEntry)).toBeNull();
    expect(resolveStringSelectChange("", optionsWithManualEntry)).toBe("");
  });

  it("rejects unknown and disabled selections", () => {
    expect(resolveStringSelectChange("unknown", options)).toBeNull();
    expect(resolveStringSelectChange("disabled", options)).toBeNull();
  });
});

describe("VStringSelect selected-key mapping", () => {
  it("keeps a declared enabled empty option selected", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <VStringSelect
          ariaLabel="Input mode"
          onValueChange={() => undefined}
          options={optionsWithManualEntry}
          placeholder="Choose input mode"
          value=""
        />
      </VuiProvider>,
    );

    expect(markup).not.toContain('data-placeholder="true"');
  });

  it("leaves an undeclared current value unselected", () => {
    const markup = renderToStaticMarkup(
      <VuiProvider>
        <VStringSelect
          ariaLabel="Input mode"
          onValueChange={() => undefined}
          options={optionsWithManualEntry}
          placeholder="Choose input mode"
          value="unknown"
        />
      </VuiProvider>,
    );

    expect(markup).toContain('data-placeholder="true"');
  });
});
