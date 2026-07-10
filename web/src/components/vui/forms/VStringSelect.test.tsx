import { describe, expect, it } from "vitest";

import { resolveStringSelectChange } from "./VStringSelect";

const options = [
  { value: "safe", label: "Safe" },
  { value: "disabled", label: "Disabled", disabled: true },
];

describe("resolveStringSelectChange", () => {
  it("returns an enabled selection", () => {
    expect(resolveStringSelectChange("safe", options)).toBe("safe");
  });

  it("rejects empty, unknown, and disabled selections", () => {
    expect(resolveStringSelectChange(null, options)).toBeNull();
    expect(resolveStringSelectChange("unknown", options)).toBeNull();
    expect(resolveStringSelectChange("disabled", options)).toBeNull();
  });
});
