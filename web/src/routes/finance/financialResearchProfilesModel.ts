import type { FinancialResearchProfile } from "../../api/financialPreferences";

export type ResearchProfileConflictReason = "changed" | "deleted" | "id_collision";

export class ResearchProfileConflictError extends Error {
  constructor(readonly reason: ResearchProfileConflictReason) {
    super("research-profile-conflict");
    this.name = "ResearchProfileConflictError";
  }
}

function sameProfileContent(left: FinancialResearchProfile, right: FinancialResearchProfile): boolean {
  return left.id === right.id
    && left.name === right.name
    && left.scope === right.scope
    && left.depth === right.depth
    && left.period === right.period
    && left.instructions === right.instructions;
}

/** Rebase edits only when the selected profile still matches the snapshot editing began from. */
export function saveResearchProfileChange(
  current: FinancialResearchProfile[],
  submitted: FinancialResearchProfile,
  editingId: string | null,
  baseline: FinancialResearchProfile | null,
): FinancialResearchProfile[] {
  if (!editingId) {
    if (current.some((profile) => profile.id === submitted.id)) throw new ResearchProfileConflictError("id_collision");
    return [...current, submitted];
  }
  if (!baseline || baseline.id !== editingId || submitted.id !== editingId) throw new ResearchProfileConflictError("deleted");
  const currentProfile = current.find((profile) => profile.id === editingId);
  if (!currentProfile) throw new ResearchProfileConflictError("deleted");
  if (!sameProfileContent(currentProfile, baseline)) throw new ResearchProfileConflictError("changed");
  return current.map((profile) => profile.id === editingId ? { ...submitted, isDefault: profile.isDefault } : profile);
}

/** A default change is its own intent and uses the latest default flags; it never recreates a missing profile. */
export function setResearchProfileDefault(current: FinancialResearchProfile[], id: string): FinancialResearchProfile[] {
  if (!current.some((profile) => profile.id === id)) throw new ResearchProfileConflictError("deleted");
  return current.map((profile) => ({ ...profile, isDefault: profile.id === id }));
}
