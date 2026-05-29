import type { AgentInstance } from "../api/types";

export type ChatMentionTarget = {
  kind: "agent" | "all";
  label: string;
  agentId?: string;
  agentCode?: string;
  displayName?: string;
  directSessionId?: string;
};

export type ChatMentionSegment =
  | { type: "text"; text: string }
  | { type: "mention"; text: string; target: ChatMentionTarget };

function normalizedMentionAlias(value: string) {
  const body = String(value ?? "").trim().replace(/^@+/, "");
  return body ? `@${body}` : "";
}

function isAsciiIdentifierChar(value: string) {
  return /^[A-Za-z0-9_-]$/.test(value);
}

function canEndMentionAt(content: string, startIndex: number, alias: string) {
  const nextChar = content[startIndex + alias.length] ?? "";
  const aliasTail = alias[alias.length - 1] ?? "";
  if (!nextChar) {
    return true;
  }
  if (isAsciiIdentifierChar(aliasTail) && isAsciiIdentifierChar(nextChar)) {
    return false;
  }
  return true;
}

export function buildChatMentionTargets(agents: AgentInstance[]): ChatMentionTarget[] {
  const byAlias = new Map<string, ChatMentionTarget>();
  const addAlias = (alias: string, target: ChatMentionTarget) => {
    const normalized = normalizedMentionAlias(alias);
    if (!normalized) {
      return;
    }
    const key = normalized.toLocaleLowerCase();
    const existing = byAlias.get(key);
    if (!existing || (!existing.directSessionId && target.directSessionId)) {
      byAlias.set(key, { ...target, label: normalized });
    }
  };

  addAlias("全体成员", { kind: "all", label: "@全体成员" });
  addAlias("all", { kind: "all", label: "@all" });

  agents
    .filter((agent) => String(agent.status ?? "").trim().toLowerCase() !== "archived")
    .forEach((agent) => {
      const target: ChatMentionTarget = {
        kind: "agent",
        label: "",
        agentId: agent.agentId,
        agentCode: agent.agentCode,
        displayName: agent.displayName,
        directSessionId: agent.directSessionId,
      };
      addAlias(agent.agentCode, target);
      addAlias(agent.displayName, target);
      addAlias(agent.agentId, target);
    });

  return [...byAlias.values()].sort((left, right) => right.label.length - left.label.length);
}

export function tokenizeChatMentions(content: string, targets: ChatMentionTarget[]): ChatMentionSegment[] {
  if (!content || !targets.length) {
    return content ? [{ type: "text", text: content }] : [];
  }

  const segments: ChatMentionSegment[] = [];
  const pushText = (text: string) => {
    const previous = segments[segments.length - 1];
    if (previous?.type === "text") {
      previous.text += text;
      return;
    }
    segments.push({ type: "text", text });
  };
  let cursor = 0;
  while (cursor < content.length) {
    if (content[cursor] !== "@") {
      const nextAt = content.indexOf("@", cursor);
      const end = nextAt >= 0 ? nextAt : content.length;
      pushText(content.slice(cursor, end));
      cursor = end;
      continue;
    }

    const matched = targets.find((target) => {
      const alias = target.label;
      return (
        content.slice(cursor, cursor + alias.length).toLocaleLowerCase() === alias.toLocaleLowerCase()
        && canEndMentionAt(content, cursor, alias)
      );
    });

    if (!matched) {
      pushText(content[cursor]);
      cursor += 1;
      continue;
    }

    segments.push({
      type: "mention",
      text: content.slice(cursor, cursor + matched.label.length),
      target: matched,
    });
    cursor += matched.label.length;
  }

  return segments;
}
