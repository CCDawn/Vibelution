/** Route/domain dictionary pack ids (D1 lazy-load). */
export const DICTIONARY_DOMAIN_IDS = [
  "core",
  "chat",
  "agents",
  "teams",
  "evolution",
  "tools",
  "git",
  "logs",
  "pet",
] as const;

export type DictionaryDomainId = (typeof DICTIONARY_DOMAIN_IDS)[number];

/** Always loaded with any route dictionary request. */
export const DICTIONARY_CORE_DOMAIN: DictionaryDomainId = "core";

export function normalizeDictionaryDomains(
  domains: readonly DictionaryDomainId[] | undefined,
): DictionaryDomainId[] {
  const selected = new Set<DictionaryDomainId>([DICTIONARY_CORE_DOMAIN]);
  for (const domain of domains ?? DICTIONARY_DOMAIN_IDS) {
    selected.add(domain);
  }
  return DICTIONARY_DOMAIN_IDS.filter((id) => selected.has(id));
}

export function dictionaryDomainsQueryKey(domains: readonly DictionaryDomainId[]) {
  return domains.join(",");
}
