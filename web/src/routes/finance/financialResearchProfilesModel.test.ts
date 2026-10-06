import { expect, it } from "vitest";
import type { FinancialResearchProfile } from "../../api/financialPreferences";
import { ResearchProfileConflictError, saveResearchProfileChange, setResearchProfileDefault } from "./financialResearchProfilesModel";

const profile: FinancialResearchProfile = {
  id: "profile-1", name: "Bank quality", scope: "financial", depth: "standard", period: "2025FY", instructions: "Margins and provisions", isDefault: false,
};

it("merges an unchanged profile edit with unrelated workspace changes and preserves its latest default flag", () => {
  const latestDefault = { ...profile, isDefault: true };
  const other: FinancialResearchProfile = { ...profile, id: "profile-2", name: "Events", isDefault: false };
  const submitted = { ...profile, name: "Bank profitability", instructions: "Margins and credit quality" };
  expect(saveResearchProfileChange([latestDefault, other], submitted, profile.id, profile)).toEqual([
    { ...submitted, isDefault: true }, other,
  ]);
});

it("rejects stale profile edits after another window changes or deletes the profile", () => {
  const submitted = { ...profile, name: "Stale draft" };
  expect(() => saveResearchProfileChange([{ ...profile, instructions: "newer content" }], submitted, profile.id, profile))
    .toThrowError(expect.objectContaining({ reason: "changed" }));
  expect(() => saveResearchProfileChange([], submitted, profile.id, profile))
    .toThrowError(expect.objectContaining({ reason: "deleted" }));
});

it("does not let a new profile ID replace an existing profile", () => {
  expect(() => saveResearchProfileChange([profile], { ...profile, name: "Collision" }, null, null))
    .toThrowError(expect.objectContaining({ reason: "id_collision" }));
});

it("applies default changes to the latest profile set without resurrecting a deleted profile", () => {
  const other = { ...profile, id: "profile-2", name: "Events", isDefault: true };
  expect(setResearchProfileDefault([profile, other], profile.id)).toEqual([
    { ...profile, isDefault: true }, { ...other, isDefault: false },
  ]);
  expect(() => setResearchProfileDefault([other], profile.id)).toThrowError(ResearchProfileConflictError);
});
