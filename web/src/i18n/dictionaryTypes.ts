/**
 * Stable TranslationKey surface without forcing the full dictionary into a runtime graph.
 * Domain modules are type-only imports here.
 */
import type { dictionaryAgents } from "./domains/dictionaryAgents";
import type { dictionaryChat } from "./domains/dictionaryChat";
import type { dictionaryCore } from "./domains/dictionaryCore";
import type { dictionaryEvolution } from "./domains/dictionaryEvolution";
import type { dictionaryGit } from "./domains/dictionaryGit";
import type { dictionaryLogs } from "./domains/dictionaryLogs";
import type { dictionaryPet } from "./domains/dictionaryPet";
import type { dictionaryTeams } from "./domains/dictionaryTeams";
import type { dictionaryTools } from "./domains/dictionaryTools";

export type Language = "zh" | "en";

export type TranslationKey =
  | keyof typeof dictionaryCore.zh
  | keyof typeof dictionaryChat.zh
  | keyof typeof dictionaryAgents.zh
  | keyof typeof dictionaryTeams.zh
  | keyof typeof dictionaryEvolution.zh
  | keyof typeof dictionaryTools.zh
  | keyof typeof dictionaryGit.zh
  | keyof typeof dictionaryLogs.zh
  | keyof typeof dictionaryPet.zh;
