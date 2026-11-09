/**
 * Short-thought expansion policy.
 *
 * A settled reasoning unit that fits in a couple of lines reads as content, not
 * as a process log: collapsing it costs more attention than showing it. Only
 * long units keep the collapsed-by-default treatment, and an explicit user
 * toggle always wins over this default.
 *
 * Kept in its own module so contract tests can pin the previous
 * "everything settles collapsed" behaviour without re-deriving the rule.
 */
export const SHORT_THOUGHT_MAX_CHARS = 240;
