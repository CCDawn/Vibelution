import { describe, expect, it } from "vitest";

import selfEvolutionSource from "./SelfEvolutionTrack.tsx?raw";

describe("SelfEvolutionTrack static assets", () => {
  it("does not use remote placeholder images that pollute runtime scene logs", () => {
    expect(selfEvolutionSource).not.toContain("http://");
    expect(selfEvolutionSource).not.toContain("https://");
    expect(selfEvolutionSource).not.toContain("<img");
  });
});
