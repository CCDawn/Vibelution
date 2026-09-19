import { describe, expect, it } from "vitest";

import {
  hasConfiguredCredential,
  markProviderOnboardingSeen,
  PROVIDER_ONBOARDING_SEEN_KEY,
  shouldAutoOpenProviderOnboarding,
  type OnboardingStorage,
} from "./onboardingGate";

function memoryStorage(): OnboardingStorage & { store: Map<string, string> } {
  const store = new Map<string, string>();
  return {
    store,
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => void store.set(key, value),
  };
}

describe("provider onboarding gate", () => {
  it("detects fresh instances by credential flags", () => {
    expect(hasConfiguredCredential([])).toBe(false);
    expect(hasConfiguredCredential([{ api_key_configured: false }])).toBe(false);
    expect(hasConfiguredCredential([{ api_key_configured: true }])).toBe(true);
  });

  it("auto-opens once per session on a fresh instance", () => {
    const storage = memoryStorage();
    expect(shouldAutoOpenProviderOnboarding([], storage)).toBe(true);
    markProviderOnboardingSeen(storage);
    expect(storage.store.get(PROVIDER_ONBOARDING_SEEN_KEY)).toBe("1");
    expect(shouldAutoOpenProviderOnboarding([], storage)).toBe(false);
  });

  it("never auto-opens when a credential already works", () => {
    const storage = memoryStorage();
    expect(shouldAutoOpenProviderOnboarding([{ api_key_configured: true }], storage)).toBe(false);
  });

  it("fails closed without storage", () => {
    expect(shouldAutoOpenProviderOnboarding([], null)).toBe(false);
    expect(() => markProviderOnboardingSeen(null)).not.toThrow();
  });
});
