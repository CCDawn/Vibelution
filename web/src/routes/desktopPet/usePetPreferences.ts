import { useEffect, useRef, useState } from "react";
import {
  fetchPetPreferencesFromBackend, readPetPreferences, savePetPreferences, savePetPreferencesToBackend,
  subscribePetPreferences, syncPetPreferencesWithBackend, type DesktopPetPreferences,
} from "./desktopPetPreferences";

export const PET_PREFERENCES_REFRESH_EVENT = "vibelution:assistant-preferences-refresh";

// All consumers in this renderer share one order: migration, edits and focus
// refreshes cannot overtake one another or replay an older backend snapshot.
let operations: Promise<unknown> = Promise.resolve();
export function enqueuePetPreferenceOperation<T>(operation: () => Promise<T>): Promise<T> {
  const next = operations.then(operation);
  operations = next.catch(() => undefined);
  return next;
}

/** One preference path for workbench and desktop, with backend persistence and local fallback. */
export function usePetPreferences(enabled = true) {
  const [preferences, setPreferences] = useState(readPetPreferences);
  const current = useRef(preferences);
  const revision = useRef(0);

  useEffect(() => subscribePetPreferences(() => {
    revision.current += 1;
    current.current = readPetPreferences();
    setPreferences(current.current);
  }), []);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;
    async function refresh(migrate = false) {
      const version = revision.current;
      const isCurrent = () => !disposed && version === revision.current;
      try {
        await enqueuePetPreferenceOperation(async () => {
          if (!isCurrent()) return;
          const next = migrate ? await syncPetPreferencesWithBackend(current.current, isCurrent)
            : await fetchPetPreferencesFromBackend();
          if (!next || !isCurrent()) return;
          current.current = next;
          setPreferences(next);
          savePetPreferences(next);
        });
      } catch { /* Retain the local cache while the settings service is unavailable. */ }
    }
    const read = () => { void refresh(); };
    void refresh(true);
    window.addEventListener("focus", read);
    window.addEventListener(PET_PREFERENCES_REFRESH_EVENT, read);
    return () => {
      disposed = true;
      window.removeEventListener("focus", read);
      window.removeEventListener(PET_PREFERENCES_REFRESH_EVENT, read);
    };
  }, [enabled]);

  function updatePreferences(patch: Partial<DesktopPetPreferences>) {
    revision.current += 1;
    const next = { ...current.current, ...patch };
    current.current = next;
    setPreferences(next);
    const local = savePetPreferences(next);
    const operation = enqueuePetPreferenceOperation(async () => {
      try {
        await savePetPreferencesToBackend(next, patch);
        return { local, backend: true };
      } catch {
        return { local, backend: false };
      }
    });
    return operation;
  }
  return { preferences, updatePreferences };
}
