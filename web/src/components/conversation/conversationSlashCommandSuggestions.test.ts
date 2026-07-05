import { describe, expect, it } from "vitest";

import type { SkillLibraryItem } from "../../api/types";
import chatRouteSource from "../../routes/ChatCodingRoute.tsx?raw";
import chatConversationComposerBridgeSource from "../../routes/chat/ChatConversationComposerBridge.tsx?raw";
import conversationViewSource from "./ConversationView.tsx?raw";
import {
  composerSlashCommandQuery,
  filterSlashCommandSuggestions,
  insertSlashCommandSuggestion,
  shouldShowSlashCommandSuggestions,
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
    expect(filterSlashCommandSuggestions(skills, "/ccd").map((item) => item.command)).toEqual(["/ccdawn-brt"]);
    expect(filterSlashCommandSuggestions(skills, "/brt").map((item) => item.command)).toEqual(["/ccdawn-brt"]);
    expect(filterSlashCommandSuggestions(skills, "/root").map((item) => item.command)).toEqual(["/systematic-debugging"]);
    expect(filterSlashCommandSuggestions(skills, "/").map((item) => item.command)).toEqual([
      "/brainstorming",
      "/ccdawn-brt",
      "/systematic-debugging",
    ]);
  });

  it("inserts the selected command with one trailing space", () => {
    expect(insertSlashCommandSuggestion("/ccd", "/ccdawn-brt")).toBe("/ccdawn-brt ");
    expect(insertSlashCommandSuggestion("  /brt", "/ccdawn-brt")).toBe("/ccdawn-brt ");
    expect(insertSlashCommandSuggestion("请用 /brt", "/ccdawn-brt")).toBe("请用 /brt");
  });

  it("wires skill library data from the route into the conversation composer", () => {
    expect(chatRouteSource).toContain('fetchJson<SkillLibraryPayload>("/api/skills")');
    expect(chatRouteSource).toContain("const slashCommandSuggestions = skillsQuery.data?.skills ?? []");
    expect(chatRouteSource).toContain("slashCommandSuggestions={slashCommandSuggestions}");
    expect(chatConversationComposerBridgeSource).toContain("slashCommandSuggestions={slashCommandSuggestions}");
    expect(conversationViewSource).toContain("filterSlashCommandSuggestions(slashCommandSuggestions, composerValue)");
    expect(conversationViewSource).toContain("insertSlashCommandSuggestion(composerValue, skill.command)");
    expect(conversationViewSource).toContain('role="listbox"');
    expect(conversationViewSource).toContain('role="option"');
  });
});
