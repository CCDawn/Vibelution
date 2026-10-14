import type { VirtualHumanSnapshot } from "../../api/types/virtualHumanLife";

export type CompanionSceneKey = "home" | "library" | "studio" | "park" | "neutral";

export type CompanionSceneSelection = {
  key: CompanionSceneKey;
  backgroundUrl: string | null;
};

export function isCompanionSceneAssetAligned(key: CompanionSceneKey, projectedSceneKey: string): boolean {
  if (key === "neutral") return false;
  const family = projectedSceneKey.toLowerCase().split("-")[0];
  return family === key || (key === "park" && family === "outdoors");
}

const BACKGROUND_URLS: Record<Exclude<CompanionSceneKey, "neutral">, string> = {
  home: new URL("./assets/scenes/room-background-v1.png", import.meta.url).href,
  library: new URL("./assets/scenes/library-background-v1.png", import.meta.url).href,
  studio: new URL("./assets/scenes/studio-background-v1.png", import.meta.url).href,
  park: new URL("./assets/scenes/park-background-v1.png", import.meta.url).href,
};

const LOCATION_SCENES: ReadonlyMap<string, Exclude<CompanionSceneKey, "neutral">> = new Map([
  ["home", "home"],
  ["house", "home"],
  ["my home", "home"],
  ["my house", "home"],
  ["家", "home"],
  ["我家", "home"],
  ["在家", "home"],
  ["我家里", "home"],
  ["家里", "home"],
  ["家中", "home"],
  ["在家中", "home"],
  ["住处", "home"],
  ["在住处", "home"],
  ["住所", "home"],
  ["住宅", "home"],
  ["居所", "home"],
  ["library", "library"],
  ["reading room", "library"],
  ["school library", "library"],
  ["图书馆", "library"],
  ["阅览室", "library"],
  ["studio", "studio"],
  ["music studio", "studio"],
  ["创作工作室", "studio"],
  ["录音室", "studio"],
  ["工作室", "studio"],
  ["park", "park"],
  ["公园", "park"],
]);

function normalizeLocation(value: string): string {
  return value
    .normalize("NFKC")
    .toLocaleLowerCase("en-US")
    .replace(/[\p{P}\p{S}]+/gu, " ")
    .replace(/\s+/g, " ")
    .trim();
}

export function selectCompanionScene(snapshot: VirtualHumanSnapshot): CompanionSceneSelection {
  const location = normalizeLocation(snapshot.state?.currentLocation ?? "");
  const key = LOCATION_SCENES.get(location) ?? "neutral";

  return {
    key,
    backgroundUrl: key === "neutral" ? null : BACKGROUND_URLS[key],
  };
}
