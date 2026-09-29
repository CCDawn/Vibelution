import { SquareSlash } from "lucide-react";

import type { SkillLibraryItem } from "../../api/types/memory";
import styles from "./ConversationSlashCommandChip.styles";

/** Oversized tokens are path/URL look-alikes, not commands. */
const MAX_SLASH_COMMAND_ECHO_TOKEN_LENGTH = 64;

export type UserSlashCommandEcho = {
  /** Command name without the leading slash. */
  command: string;
  /** Everything after the command token, leading whitespace trimmed. */
  rest: string;
};

export type UserSlashCommandTone = "skill" | "unknown";

/**
 * Splits a leading `/token` off user message text for the timeline echo chip.
 *
 * The text prefix is the authoritative carrier: the composer submits the raw
 * draft (`/command args`), optimistic rows carry no metadata, and unknown
 * commands get no backend `slashSkillCommand` metadata — yet all of them must
 * chip. So the parse never consults metadata. Absolute-path look-alikes
 * (`/etc/hosts` — the whitespace-delimited token carries a second `/`) and
 * oversized tokens stay plain text; a bare `/` is not a command.
 */
export function parseUserSlashCommandEcho(text: string): UserSlashCommandEcho | null {
  const trimmed = String(text || "").replace(/^\s+/, "");
  if (!trimmed.startsWith("/")) {
    return null;
  }
  const token = trimmed.split(/\s+/, 1)[0] ?? "";
  const command = token.slice(1);
  if (!command || command.includes("/") || command.length > MAX_SLASH_COMMAND_ECHO_TOKEN_LENGTH) {
    return null;
  }
  return { command, rest: trimmed.slice(token.length).replace(/^\s+/, "") };
}

function slashlessCommandToken(value: string): string {
  return String(value || "").replace(/^\/+/, "").trim().toLowerCase();
}

/**
 * Known-command lookup over the composer's skill library (same source the
 * suggestion listbox ranks). Command and aliases compare slashless and
 * case-insensitively; anything else renders in the neutral tone.
 */
export function resolveUserSlashCommandTone(
  command: string,
  skills: SkillLibraryItem[],
): UserSlashCommandTone {
  const wanted = slashlessCommandToken(command);
  if (!wanted) {
    return "unknown";
  }
  for (const skill of skills) {
    const candidates = [skill.command, ...(Array.isArray(skill.aliases) ? skill.aliases : [])];
    if (candidates.some((candidate) => slashlessCommandToken(candidate) === wanted)) {
      return "skill";
    }
  }
  return "unknown";
}

/**
 * Timeline echo chip for a user message's leading slash command (ZCode
 * ConversationUserInputContent parity): a rounded command block that reads as
 * an executed command, not prose. Presentational only — copy, edit and the
 * protocol keep the original raw text.
 */
export function ConversationSlashCommandChip({
  command,
  tone,
}: {
  command: string;
  tone: UserSlashCommandTone;
}) {
  return (
    <span
      className={tone === "skill" ? styles.chipSkill : styles.chipUnknown}
      data-testid="user-slash-command-chip"
      data-slash-command-tone={tone}
    >
      <SquareSlash aria-hidden="true" className={styles.chipIcon} size={14} />
      <span className={styles.chipCommand}>/{command}</span>
    </span>
  );
}
