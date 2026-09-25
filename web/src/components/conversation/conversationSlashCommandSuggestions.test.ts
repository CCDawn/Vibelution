import { describe, expect, it } from "vitest";

import type { SkillLibraryItem } from "../../api/types";
import chatRouteSource from "../../routes/chat/ChatCodingRouteWorkbench.tsx?raw";
import chatCatalogQueriesSource from "../../routes/chat/useChatWorkbenchCatalogQueries.ts?raw";
import chatConversationComposerBridgeSource from "../../routes/chat/ChatConversationComposerBridge.tsx?raw";
import chatSessionWorkspacePanelSource from "../../routes/chat/ChatSessionWorkspacePanel.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  composerSlashCommandQuery,
  filterSlashCommandSuggestions,
  insertSlashCommandSuggestion,
  mergeSlashCommandSuggestions,
  moveSlashCommandActiveIndex,
  shouldShowSlashCommandSuggestions,
  type BuiltinSlashCommand,
} from "./conversationSlashCommandSuggestions";

function skill(command: string, description = "", aliases: string[] = []): SkillLibraryItem {
  return {
    name: command.replace("/", ""),
    aliases,
    command,
    description,
    source: "codex",
    rootPath: "C:/Users/17533/.codex/skills",
    path: `C:/Users/17533/.codex/skills/${command.replace("/", "")}/SKILL.md`,
    directoryName: command.replace("/", ""),
    hash: "hash",
    contentLength: 100,
    preview: "",
    previewTruncated: false,
  };
}

function builtin(command: string, id: BuiltinSlashCommand["id"] = "new_session", aliases: string[] = []): BuiltinSlashCommand {
  return { id, command, aliases, description: `${command} description` };
}

describe("conversation slash command suggestions", () => {
  const skills = [
    skill("/ccdawn-brt", "Chinese-first intent routing", ["ccdawn-brt", "brt"]),
    skill("/systematic-debugging", "Find root causes before fixes", ["systematic-debugging"]),
    skill("/brainstorming", "Explore requirements before implementation", ["brainstorming"]),
  ];

  it("opens only for a leading slash command draft without spaces", () => {
    expect(shouldShowSlashCommandSuggestions("/")).toBe(true);
    expect(shouldShowSlashCommandSuggestions("/ccd")).toBe(true);
    expect(shouldShowSlashCommandSuggestions(" /ccd")).toBe(true);
    expect(shouldShowSlashCommandSuggestions("/ccdawn-brt 继续")).toBe(false);
    expect(shouldShowSlashCommandSuggestions("请用 /ccdawn-brt")).toBe(false);
  });

  it("extracts the current slash query without the slash", () => {
    expect(composerSlashCommandQuery("/")).toBe("");
    expect(composerSlashCommandQuery("/ccd")).toBe("ccd");
    expect(composerSlashCommandQuery("  /debug")).toBe("debug");
  });

  it("filters skills by command, alias, name, and description", () => {
    // The English subsequence tier adds low-priority matches (a query's
    // characters scattered across a haystack) below exact contains matches.
    expect(filterSlashCommandSuggestions(skills, "/ccd").map((item) => item.command)).toEqual([
      "/ccdawn-brt",
      "/systematic-debugging",
    ]);
    expect(filterSlashCommandSuggestions(skills, "/brt").map((item) => item.command)).toEqual([
      "/ccdawn-brt",
      "/brainstorming",
      "/systematic-debugging",
    ]);
    expect(filterSlashCommandSuggestions(skills, "/root").map((item) => item.command)).toEqual([
      "/systematic-debugging",
      "/brainstorming",
    ]);
    expect(filterSlashCommandSuggestions(skills, "/").map((item) => item.command)).toEqual([
      "/brainstorming",
      "/ccdawn-brt",
      "/systematic-debugging",
    ]);
  });

  it("ranks skill substring matches above subsequence matches", () => {
    const englishSkills = [
      skill("/abc", "r-o-a-d markers"),
      skill("/x-road", "road mapping"),
    ];
    // Alphabetical order alone would put "/abc" first; the substring tier wins.
    expect(filterSlashCommandSuggestions(englishSkills, "/road").map((item) => item.command)).toEqual([
      "/x-road",
      "/abc",
    ]);
  });

  it("ranks a command-prefix match above a substring match for /b", () => {
    const bSkills = [skill("/abc-tool", "bug tracking"), skill("/bug-report", "report bugs")];
    // "/b" drops its slash before scoring, so "/bug-report" must still reach
    // the prefix tier via the slashless haystack token and beat "/abc-tool",
    // which only contains the query and would win an alphabetical tie.
    expect(filterSlashCommandSuggestions(bSkills, "/b").map((item) => item.command)).toEqual([
      "/bug-report",
      "/abc-tool",
    ]);
  });

  it("does not match CJK skills through scattered characters", () => {
    const cjkSkills = [skill("/杂谈", "这里文散着件字")];
    expect(filterSlashCommandSuggestions(cjkSkills, "/文件")).toEqual([]);
  });

  it("merges builtins before skills and flags builtin rows", () => {
    const builtins = [
      builtin("/新会话", "new_session", ["new", "session"]),
      builtin("/模型", "model", ["model"]),
      builtin("/压缩", "compress_context", ["compact", "compress"]),
    ];
    const merged = mergeSlashCommandSuggestions(builtins, skills, "/");
    expect(merged.map((item) => item.command)).toEqual([
      "/新会话",
      "/模型",
      "/压缩",
      "/brainstorming",
      "/ccdawn-brt",
      "/systematic-debugging",
    ]);
    expect(merged.slice(0, 3).every((item) => item.builtin && item.builtinId)).toBe(true);
    expect(merged.slice(3).every((item) => !item.builtin && item.skill)).toBe(true);
    expect(merged[0].key).toBe("builtin:new_session");
    expect(merged[3].key).toBe("skill:/brainstorming");
  });

  it("filters builtins by command, alias, and description", () => {
    const builtins = [
      builtin("/新会话", "new_session", ["new", "session"]),
      builtin("/模型", "model", ["model"]),
      builtin("/压缩", "compress_context", ["compact", "compress"]),
    ];
    expect(mergeSlashCommandSuggestions(builtins, skills, "/新").map((item) => item.command)).toEqual(["/新会话"]);
    // "new" still wins on the builtin alias; the English subsequence tier adds
    // a low-priority skill hit (n..e..w across "chinese ... ccdawn").
    expect(mergeSlashCommandSuggestions(builtins, skills, "/new").map((item) => item.command)).toEqual([
      "/新会话",
      "/ccdawn-brt",
    ]);
    expect(mergeSlashCommandSuggestions(builtins, skills, "/compact").map((item) => item.command)).toEqual(["/压缩"]);
    expect(mergeSlashCommandSuggestions(builtins, skills, "/zzz")).toEqual([]);
  });

  it("keeps the builtin-first, skills-alphabetical layout when scores tie", () => {
    const builtins = [builtin("/model", "model", ["mode"])];
    const tieSkills = [skill("/modem", "dial-up lines"), skill("/model-kit", "kit parts")];
    const merged = mergeSlashCommandSuggestions(builtins, tieSkills, "/mode");
    expect(merged.map((item) => item.command)).toEqual(["/model", "/model-kit", "/modem"]);
  });

  it("ranks a stronger skill match above a weaker builtin match", () => {
    const builtins = [builtin("/model", "model", ["mode"])];
    const betterSkills = [skill("/mdl-tools", "mdl helpers")];
    // "mdl" only subsequence-matches the builtin ("/model" m..d..l) but
    // substring-matches the skill, so the skill outranks the builtin.
    expect(mergeSlashCommandSuggestions(builtins, betterSkills, "/mdl").map((item) => item.command)).toEqual([
      "/mdl-tools",
      "/model",
    ]);
  });

  it("ranks /new_session first for /new via the prefix tier", () => {
    // Without the slashless haystack token the builtin only substring-matches
    // ("new" lives in its alias) and loses to the "/newbie-guide" prefix hit.
    const builtins = [builtin("/new_session", "new_session", ["new", "session"])];
    const newSkills = [skill("/newbie-guide", "guide for newcomers")];
    expect(mergeSlashCommandSuggestions(builtins, newSkills, "/new").map((item) => item.command)).toEqual([
      "/new_session",
      "/newbie-guide",
    ]);
  });

  it("only offers builtin commands whose channels exist", () => {
    const onlyCompress = [builtin("/压缩", "compress_context")];
    expect(mergeSlashCommandSuggestions(onlyCompress, skills, "/").map((item) => item.command)).toEqual([
      "/压缩",
      "/brainstorming",
      "/ccdawn-brt",
      "/systematic-debugging",
    ]);
  });

  it("caps the merged list like the skill-only path", () => {
    const builtins = [
      builtin("/一", "new_session"),
      builtin("/二", "model"),
      builtin("/三", "compress_context"),
    ];
    const merged = mergeSlashCommandSuggestions(builtins, skills, "/", 4);
    expect(merged).toHaveLength(4);
    expect(merged.map((item) => item.command)).toEqual(["/一", "/二", "/三", "/brainstorming"]);
  });

  it("cycles the active suggestion index in both directions", () => {
    expect(moveSlashCommandActiveIndex(-1, 1, 3)).toBe(0);
    expect(moveSlashCommandActiveIndex(0, 1, 3)).toBe(1);
    expect(moveSlashCommandActiveIndex(2, 1, 3)).toBe(0);
    expect(moveSlashCommandActiveIndex(0, -1, 3)).toBe(2);
    expect(moveSlashCommandActiveIndex(1, 1, 0)).toBe(-1);
  });

  it("inserts the selected command with one trailing space", () => {
    expect(insertSlashCommandSuggestion("/ccd", "/ccdawn-brt")).toBe("/ccdawn-brt ");
    expect(insertSlashCommandSuggestion("  /brt", "/ccdawn-brt")).toBe("/ccdawn-brt ");
    expect(insertSlashCommandSuggestion("请用 /brt", "/ccdawn-brt")).toBe("请用 /brt");
  });

  it("wires skill library data and the builtin merge into the conversation composer", () => {
    expect(chatCatalogQueriesSource).toContain("fetchSkillLibrary");
    expect(chatCatalogQueriesSource).toContain("const slashCommandSuggestions = skillsQuery.data?.skills ?? []");
    expect(chatRouteSource).toContain("useChatWorkbenchCatalogQueries");
    expect(chatRouteSource).toContain("slashCommandSuggestions,");
    expect(chatRouteSource).toContain("onCreateSession: !verifiedCompanionMode && selectedChatAgent");
    expect(chatSessionWorkspacePanelSource).toContain('type ConversationBridgeProps = Omit<ComponentProps<typeof ChatConversationComposerBridge>, "fallback">');
    expect(chatSessionWorkspacePanelSource).toContain("{...conversation}");
    expect(chatConversationComposerBridgeSource).toContain("slashCommandSuggestions={slashCommandSuggestions}");
    expect(conversationViewSource).toContain("mergeSlashCommandSuggestions(");
    expect(conversationViewSource).toContain("insertSlashCommandSuggestion(composerValue, suggestion.skill.command)");
    expect(conversationViewSource).toContain('role="listbox"');
    expect(conversationViewSource).toContain('role="option"');
    expect(conversationViewSource).toContain("executeBuiltinSlashCommand(suggestion.builtinId)");
    expect(conversationViewSource).toContain('data-vui="slash-builtin-badge"');
  });
});
