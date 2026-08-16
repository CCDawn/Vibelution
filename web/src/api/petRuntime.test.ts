import { describe, expect, it } from "vitest";

import petApiSource from "./pet.ts?raw";
import runtimeApiSource from "./runtime.ts?raw";
import petRouteSource from "../routes/PetRoute.tsx?raw";
import selfTrackSource from "../routes/SelfEvolutionTrack.tsx?raw";

describe("pet and runtime catalog API", () => {
  it("owns pet and runtime summary transports", () => {
    expect(petApiSource).toContain("export function fetchPetSummary");
    expect(runtimeApiSource).toContain("export function fetchRuntimeSummary");
    expect(petApiSource).toContain('"/api/pet/summary"');
    expect(runtimeApiSource).toContain('"/api/runtime/summary"');
  });

  it("keeps PetRoute and SelfEvolutionTrack free of inline paths", () => {
    expect(petRouteSource).toContain("fetchPetSummary(");
    expect(petRouteSource).not.toContain("/api/pet/");
    expect(selfTrackSource).toContain("fetchPetSummary(");
    expect(selfTrackSource).toContain("fetchRuntimeSummary(");
    expect(selfTrackSource).not.toContain("/api/pet/");
    expect(selfTrackSource).not.toContain("/api/runtime/");
  });
});
