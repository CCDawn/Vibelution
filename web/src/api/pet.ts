import { fetchJson } from "./client";
import type { PetActionResponse, PetSummary } from "./types";

export function fetchPetSummary(): Promise<PetSummary> {
  return fetchJson<PetSummary>("/api/pet/summary");
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
