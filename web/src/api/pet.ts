import { fetchJson } from "./client";
import type { PetActionResponse, PetSummary } from "./types";
import type { PetActivity } from "./types/petActivity";

export function fetchPetSummary(): Promise<PetSummary> {
  return fetchJson<PetSummary>("/api/pet/summary");
}

export function fetchPetActivity(): Promise<PetActivity> {
  return fetchJson<PetActivity>("/api/pet/activity");
}

export function postPetAction(action: "feed" | "talk" | "care"): Promise<PetActionResponse> {
  return fetchJson<PetActionResponse>("/api/pet/actions", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ action }),
  });
}
