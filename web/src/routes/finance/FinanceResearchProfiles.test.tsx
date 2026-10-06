// @vitest-environment happy-dom

import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { FinancialResearchProfile } from "../../api/financialPreferences";
import type { FinanceResearchConfigValue } from "./FinanceResearchConfig";
import { FinanceResearchProfiles } from "./FinanceResearchProfiles";
import { saveResearchProfileChange } from "./financialResearchProfilesModel";

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
const profile: FinancialResearchProfile = {
  id: "profile-1", name: "Bank quality", scope: "financial", depth: "standard", period: "2025FY", instructions: "Margins and provisions", isDefault: false,
};
const value: FinanceResearchConfigValue = { period: profile.period, date: "2026-10-06", scope: profile.scope, depth: profile.depth, instructions: profile.instructions };
let root: Root | null = null;
let container: HTMLDivElement;

function button(label: string): HTMLButtonElement {
  const found = [...container.querySelectorAll("button")].find((item) => item.textContent?.includes(label));
  if (!found) throw new Error(`Button not found: ${label}`);
  return found;
}

function setInputValue(input: HTMLInputElement, next: string) {
  const setter = Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set;
  setter?.call(input, next);
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

beforeEach(() => {
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
});

afterEach(async () => {
  await act(async () => root?.unmount());
  root = null;
  container.remove();
});

describe("FinanceResearchProfiles conflict behavior", () => {
  it("keeps the original edit baseline and visible draft when a concurrent profile change is rejected", async () => {
    const onSave = vi.fn(async (change: (current: FinancialResearchProfile[]) => FinancialResearchProfile[]) =>
      change([{ ...profile, instructions: "Changed in another window" }])
    );
    const props = {
      ready: true,
      value,
      onChange: vi.fn(),
      onSave,
      pending: false,
      zh: true,
      selectedProfileId: profile.id,
      onSelectProfile: vi.fn(),
    };
    await act(async () => root?.render(<FinanceResearchProfiles profiles={[profile]} {...props} />));

    const name = container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]');
    expect(name?.value).toBe(profile.name);
    await act(async () => setInputValue(name!, "My unsaved draft"));
    await act(async () => root?.render(<FinanceResearchProfiles profiles={[{ ...profile, instructions: "Changed in another window" }]} {...props} />));
    expect(container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]')?.value).toBe("My unsaved draft");

    await act(async () => button("保存设置").click());

    expect(onSave).toHaveBeenCalledOnce();
    expect(container.textContent).toContain("该研究档案已在其他窗口修改");
    expect(container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]')?.value).toBe("My unsaved draft");
  });

  it("keeps the profile draft visible when the selected profile was deleted during conflict replay", async () => {
    const onSelectProfile = vi.fn();
    const onSave = vi.fn(async (change: (current: FinancialResearchProfile[]) => FinancialResearchProfile[]) => change([]));
    await act(async () => root?.render(<FinanceResearchProfiles profiles={[profile]} ready value={value} onChange={vi.fn()} onSave={onSave} pending={false} zh selectedProfileId={profile.id} onSelectProfile={onSelectProfile} />));
    const name = container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]');
    await act(async () => setInputValue(name!, "Draft after deletion"));
    await act(async () => button("保存设置").click());

    expect(container.textContent).toContain("该研究档案已在其他窗口删除");
    expect(container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]')?.value).toBe("Draft after deletion");
    expect(onSelectProfile).not.toHaveBeenCalled();
  });

  it("does not steal a newer selection when an older save completes late", async () => {
    const other: FinancialResearchProfile = { ...profile, id: "profile-2", name: "Technology" };
    let resolveSave!: () => void;
    const saveResult = new Promise<void>((resolve) => { resolveSave = resolve; });
    const onSelectProfile = vi.fn();
    const onSave = vi.fn(() => saveResult);
    const props = { ready: true, value, onChange: vi.fn(), onSave, pending: false, zh: true, onSelectProfile };
    await act(async () => root?.render(<FinanceResearchProfiles profiles={[profile, other]} selectedProfileId={profile.id} {...props} />));
    await act(async () => button("保存设置").click());

    await act(async () => root?.render(<FinanceResearchProfiles profiles={[profile, other]} selectedProfileId={other.id} {...props} />));
    expect(container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]')?.value).toBe(other.name);
    await act(async () => { resolveSave(); await saveResult; });
    await act(async () => new Promise((resolve) => setTimeout(resolve, 0)));

    expect(onSelectProfile).not.toHaveBeenCalled();
    expect(container.querySelector<HTMLInputElement>('input[aria-label="档案名称"]')?.value).toBe(other.name);
  });
});
