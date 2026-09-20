/**
 * First-run provider onboarding gate: auto-open the provider quick-setup
 * panel once per browser session when no model credential is configured yet.
 * Pure logic with an injected storage so tests need no DOM.
 */
export const PROVIDER_ONBOARDING_SEEN_KEY = "vibelution.config.providerOnboarding.seen";

export type OnboardingStorage = Pick<Storage, "getItem" | "setItem">;

export type ModelCredentialOption = {
  api_key_configured?: boolean;
};

function resolveStorage(storage?: OnboardingStorage | null): OnboardingStorage | null {
  if (storage !== undefined) {
    return storage;
  }
  if (typeof window === "undefined" || !window.sessionStorage) {
    return null;
  }
  try {
    return window.sessionStorage;
  } catch {
    return null;
  }
}

export function hasConfiguredCredential(modelOptions: ModelCredentialOption[]): boolean {
  return modelOptions.some((option) => option.api_key_configured === true);
}

export function shouldAutoOpenProviderOnboarding(
  modelOptions: ModelCredentialOption[],
  storage?: OnboardingStorage | null,
): boolean {
  if (hasConfiguredCredential(modelOptions)) {
    return false;
  }
  const resolved = resolveStorage(storage);
  if (!resolved) {
    return false;
  }
  try {
    return resolved.getItem(PROVIDER_ONBOARDING_SEEN_KEY) !== "1";
  } catch {
    return false;
  }
}

export function markProviderOnboardingSeen(storage?: OnboardingStorage | null): void {
  const resolved = resolveStorage(storage);
  if (!resolved) {
    return;
  }
  try {
    resolved.setItem(PROVIDER_ONBOARDING_SEEN_KEY, "1");
  } catch {
    // Private mode / quota: never block the route on telemetry-like state.
  }
}
