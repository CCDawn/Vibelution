/**
 * Split web/src/i18n/dictionary.ts into domain slices under domains/.
 * Usage: node web/scripts/split-dictionary-domains.mjs
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

// script lives at web/scripts/ → repo root is ../..
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const dictPath = path.join(root, "web/src/i18n/dictionary.ts");
const outDir = path.join(root, "web/src/i18n/domains");
const src = fs.readFileSync(dictPath, "utf8");

function extractLangBody(source, lang) {
  const marker = `${lang}: {`;
  const idx = source.indexOf(marker);
  if (idx < 0) {
    throw new Error(`missing ${lang}`);
  }
  let i = idx + marker.length;
  let depth = 1;
  const start = i;
  while (i < source.length && depth > 0) {
    const c = source[i];
    if (c === "{") depth += 1;
    else if (c === "}") depth -= 1;
    i += 1;
  }
  return source.slice(start, i - 1);
}

function parseEntries(body) {
  const entries = [];
  const re = /^\s{4}([a-zA-Z_][a-zA-Z0-9_]*)\s*:\s*("(?:\\.|[^"\\])*"),?\s*$/gm;
  let match;
  while ((match = re.exec(body))) {
    entries.push({ key: match[1], value: match[2] });
  }
  return entries;
}

function domainOf(key) {
  if (key.startsWith("git")) return "git";
  if (
    key.startsWith("pet")
    || ["vitals", "mood", "hunger", "energy", "health", "love", "progress", "state", "heart", "dream", "dailyTokens", "achievements"].includes(key)
  ) {
    return "pet";
  }
  if (key.startsWith("tool") || key.startsWith("skill") || key.startsWith("image2")) return "tools";
  if (key.startsWith("log")) return "logs";
  if (
    key.startsWith("self")
    || key.startsWith("supervis")
    || key.startsWith("proposal")
    || key.startsWith("worktree")
    || key.startsWith("dataset")
    || key.startsWith("runEvent")
    || key.startsWith("activeRun")
    || key.startsWith("intake")
    || key.startsWith("closedLoop")
    || key.startsWith("evolution")
    || key.startsWith("library")
    || key.startsWith("mental")
    || key.includes("Workbench")
    || key.startsWith("workbench")
    || key.startsWith("sourceKind")
    || key.startsWith("sourceDataset")
    || key.startsWith("sourceBundle")
    || key.startsWith("sourceOfficial")
    || key.startsWith("decision_")
    || key.startsWith("risk_")
    || key.startsWith("actionApply")
    || key.startsWith("actionActivate")
    || key.startsWith("actionRollback")
    || key === "reviewWorkspace"
    || key === "runs"
    || key === "library"
    || key === "live"
    || key.startsWith("navEvolution")
    || key.startsWith("navSupervised")
    || key.startsWith("navSelf")
  ) {
    return "evolution";
  }
  if (
    key.startsWith("team")
    || key.startsWith("research")
    || key.startsWith("sourceCollection")
    || key.startsWith("experiment")
    || key.startsWith("challenge")
    || key.startsWith("workflow")
    || key.startsWith("candidate")
    || key.startsWith("knowledgeCollection")
    || key.startsWith("aiSearch")
    || key.startsWith("navTeams")
    || key.startsWith("navResearch")
  ) {
    return "teams";
  }
  if (
    key.startsWith("agent")
    || key.startsWith("memory")
    || key.startsWith("config")
    || key.startsWith("compress")
    || key.startsWith("persona")
    || key.startsWith("membership")
    || key.startsWith("bulk")
    || key.startsWith("archive")
    || key.startsWith("purge")
    || key.startsWith("inbox")
    || key.startsWith("avatar")
    || key.startsWith("governance")
    || key.startsWith("contextCompression")
    || key.startsWith("llm")
    || key.startsWith("promptTemplate")
    || key.startsWith("modeMembership")
    || key.startsWith("delegation")
    || key.startsWith("supervision")
    || key.startsWith("resetAgent")
    || key.startsWith("createAgent")
    || key.startsWith("navAgents")
    || key.startsWith("navMemory")
    || key.startsWith("navConfig")
  ) {
    return "agents";
  }
  if (
    key.startsWith("chat")
    || key.startsWith("conversa")
    || key.startsWith("session")
    || key.startsWith("editMess")
    || key.startsWith("cache")
    || key.startsWith("clearSes")
    || key.startsWith("addSessi")
    || key.startsWith("group")
    || key.startsWith("composer")
    || key.startsWith("message")
    || key.startsWith("turn")
    || key.startsWith("streaming")
    || key.startsWith("token")
    || key.startsWith("cliAgent")
    || key.startsWith("filePreview")
    || key.startsWith("toolApproval")
    || key.startsWith("response")
    || key.startsWith("navChat")
  ) {
    return "chat";
  }
  return "core";
}

const zhEntries = parseEntries(extractLangBody(src, "zh"));
const enEntries = parseEntries(extractLangBody(src, "en"));
const enMap = Object.fromEntries(enEntries.map((e) => [e.key, e.value]));

if (zhEntries.length !== enEntries.length) {
  console.error(`key count mismatch zh=${zhEntries.length} en=${enEntries.length}`);
  process.exit(1);
}

const domains = {};
for (const entry of zhEntries) {
  if (!(entry.key in enMap)) {
    console.error(`missing en key: ${entry.key}`);
    process.exit(1);
  }
  const domain = domainOf(entry.key);
  domains[domain] ??= [];
  domains[domain].push({ key: entry.key, zh: entry.value, en: enMap[entry.key] });
}

fs.mkdirSync(outDir, { recursive: true });

const exportNames = {
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

for (const [domain, entries] of Object.entries(domains)) {
  const exportName = exportNames[domain] ?? `dictionary${domain[0].toUpperCase()}${domain.slice(1)}`;
  const zhLines = entries.map((e) => `    ${e.key}: ${e.zh},`).join("\n");
  const enLines = entries.map((e) => `    ${e.key}: ${e.en},`).join("\n");
  const content = `/** Route/domain dictionary slice: ${domain} (${entries.length} keys). */
export const ${exportName} = {
  zh: {
${zhLines}
  },
  en: {
${enLines}
  },
} as const;
`;
  fs.writeFileSync(path.join(outDir, `${exportName}.ts`), content);
  console.log(`${domain}: ${entries.length} -> ${exportName}.ts`);
}

// Write index + dictionary reassembly
const importLines = Object.entries(exportNames)
  .filter(([domain]) => domains[domain])
  .map(([domain, name]) => `import { ${name} } from "./domains/${name}";`)
  .join("\n");

const mergeZh = Object.values(exportNames)
  .filter((name) => Object.values(exportNames).includes(name) && fs.existsSync(path.join(outDir, `${name}.ts`)))
  .map((name) => `  ...${name}.zh,`)
  .join("\n");
const mergeEn = Object.values(exportNames)
  .filter((name) => fs.existsSync(path.join(outDir, `${name}.ts`)))
  .map((name) => `  ...${name}.en,`)
  .join("\n");

const dictionaryTs = `export type Language = "zh" | "en";

/**
 * Full app dictionary assembled from route/domain slices under ./domains/.
 * Import domain modules only when building route-scoped i18n packs;
 * useAppI18n continues to consume this merged table for a stable TranslationKey surface.
 */
${importLines}

export const dictionary = {
  zh: {
${mergeZh}
  },
  en: {
${mergeEn}
  },
} as const;

export type TranslationKey = keyof typeof dictionary.zh;
`;

fs.writeFileSync(dictPath, dictionaryTs);
console.log("rewrote dictionary.ts as domain merge");
console.log("domains:", Object.fromEntries(Object.entries(domains).map(([k, v]) => [k, v.length])));
