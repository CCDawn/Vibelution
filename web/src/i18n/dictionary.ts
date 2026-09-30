/**
 * Full app dictionary assembled from route/domain slices under ./domains/.
 * Prefer `useAppI18n({ domains })` + dynamic domain load for route packs (D1).
 * This merge façade remains for tests, parity locks, and non-lazy consumers.
 */
import { dictionaryAgents } from "./domains/dictionaryAgents";
import { dictionaryChat } from "./domains/dictionaryChat";
import { dictionaryCore } from "./domains/dictionaryCore";
import { dictionaryEvolution } from "./domains/dictionaryEvolution";
import { dictionaryGit } from "./domains/dictionaryGit";
import { dictionaryLogs } from "./domains/dictionaryLogs";
import { dictionaryPet } from "./domains/dictionaryPet";
import { dictionarySessionArchive } from "./domains/dictionarySessionArchive";
import { dictionaryTeams } from "./domains/dictionaryTeams";
import { dictionaryTools } from "./domains/dictionaryTools";

export type { Language, TranslationKey } from "./dictionaryTypes";

export const dictionary = {
  zh: {
    ...dictionaryCore.zh,
    ...dictionaryChat.zh,
    ...dictionaryAgents.zh,
    ...dictionaryTeams.zh,
    ...dictionaryEvolution.zh,
    ...dictionaryTools.zh,
    ...dictionaryGit.zh,
    ...dictionaryLogs.zh,
    ...dictionaryPet.zh,
    ...dictionarySessionArchive.zh,
  },
  en: {
    ...dictionaryCore.en,
    ...dictionaryChat.en,
    ...dictionaryAgents.en,
    ...dictionaryTeams.en,
    ...dictionaryEvolution.en,
    ...dictionaryTools.en,
    ...dictionaryGit.en,
    ...dictionaryLogs.en,
    ...dictionaryPet.en,
    ...dictionarySessionArchive.en,
  },
} as const;
