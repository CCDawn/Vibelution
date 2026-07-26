import type { Language } from "./dictionaryTypes";
import {
  DICTIONARY_DOMAIN_IDS,
  type DictionaryDomainId,
  normalizeDictionaryDomains,
} from "./dictionaryDomainIds";

export type DictionaryLangTable = Record<string, string>;

export type LoadedDictionary = {
  zh: DictionaryLangTable;
  en: DictionaryLangTable;
};

type DomainModule = {
  dictionaryCore?: LoadedDictionary;
  dictionaryChat?: LoadedDictionary;
  dictionaryAgents?: LoadedDictionary;
  dictionaryTeams?: LoadedDictionary;
  dictionaryEvolution?: LoadedDictionary;
  dictionaryTools?: LoadedDictionary;
  dictionaryGit?: LoadedDictionary;
  dictionaryLogs?: LoadedDictionary;
  dictionaryPet?: LoadedDictionary;
};

const domainLoaders: Record<DictionaryDomainId, () => Promise<DomainModule>> = {
  core: () => import("./domains/dictionaryCore"),
  chat: () => import("./domains/dictionaryChat"),
  agents: () => import("./domains/dictionaryAgents"),
  teams: () => import("./domains/dictionaryTeams"),
  evolution: () => import("./domains/dictionaryEvolution"),
  tools: () => import("./domains/dictionaryTools"),
  git: () => import("./domains/dictionaryGit"),
  logs: () => import("./domains/dictionaryLogs"),
  pet: () => import("./domains/dictionaryPet"),
};

const domainExportName: Record<DictionaryDomainId, keyof DomainModule> = {
  core: "dictionaryCore",
  chat: "dictionaryChat",
  agents: "dictionaryAgents",
  teams: "dictionaryTeams",
  evolution: "dictionaryEvolution",
  tools: "dictionaryTools",
  git: "dictionaryGit",
  logs: "dictionaryLogs",
  pet: "dictionaryPet",
};

const domainCache = new Map<DictionaryDomainId, Promise<LoadedDictionary>>();

function loadDomain(domain: DictionaryDomainId): Promise<LoadedDictionary> {
  const cached = domainCache.get(domain);
  if (cached) {
    return cached;
  }
  const pending = domainLoaders[domain]().then((module) => {
    const exportName = domainExportName[domain];
    const slice = module[exportName];
    if (!slice) {
      throw new Error(`dictionary domain missing export: ${domain}`);
    }
    return {
      zh: { ...slice.zh },
      en: { ...slice.en },
    } as LoadedDictionary;
  });
  domainCache.set(domain, pending);
  return pending;
}

export async function loadDictionaryDomains(
  domains?: readonly DictionaryDomainId[],
): Promise<LoadedDictionary> {
  const ordered = normalizeDictionaryDomains(domains);
  const slices = await Promise.all(ordered.map((domain) => loadDomain(domain)));
  const zh: DictionaryLangTable = {};
  const en: DictionaryLangTable = {};
  for (const slice of slices) {
    Object.assign(zh, slice.zh);
    Object.assign(en, slice.en);
  }
  return { zh, en };
}

/**
 * Fire-and-forget warm of domain packs (module cache + dictionary domain cache).
 * Safe to call from soft navigation preload paths.
 */
export function prefetchDictionaryDomains(domains?: readonly DictionaryDomainId[]): void {
  void loadDictionaryDomains(domains).catch(() => {
    // Soft prefetch must not surface; next useAppI18n load will retry.
  });
}

export function dictionaryTableForLang(
  dictionary: LoadedDictionary,
  lang: Language,
): DictionaryLangTable {
  return lang === "en" ? dictionary.en : dictionary.zh;
}

/** Test/helper: which domain packs are known to the loader map. */
export function knownDictionaryDomainIds(): readonly DictionaryDomainId[] {
  return DICTIONARY_DOMAIN_IDS;
}
