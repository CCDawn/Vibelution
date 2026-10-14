import { readdirSync, readFileSync } from "node:fs";
import { relative, resolve } from "node:path";
import { describe, expect, it } from "vitest";

/**
 * Shared P0 rules: alpha utilities stay forbidden, large fixed radii retain
 * their ceiling, and existing literal spacing debt may only shrink.
 * Font sizes and literal radii are owned by vuiTypeScaleContract and the
 * per-file visualTokenEscalationContract ratchet. Do not duplicate their
 * baselines with a second, stale repository-wide total here.
 */

const srcRoot = resolve(import.meta.dirname);

const FIXED_RADIUS = /rounded-(?:2xl|3xl)\b/g;
const ALPHA_UTILITY = /\b(?:text|bg|border|ring|fill|stroke)-(?:white|black)\/[0-9]+/g;
const LITERAL_SPACING = /\b(?:p|px|py|pt|pb|pl|pr|m|mx|my|mt|mb|ml|mr|gap|space-x|space-y)-\[[0-9.]+(?:px|rem)\]/g;

// Existing main debt at abac9115b. Exact values are tied to their original
// file: removing debt elsewhere cannot fund new violations or larger values.
const SPACING_DEBT: Record<string, Record<string, number>> = {
  "routes/AgentConversationDirectory.styles.ts": { "py-[7px]": 1 },
  "components/conversation/ConversationView.styles.ts": {
    "mb-[18px]": 1, "mb-[10px]": 1, "mt-[18px]": 1, "py-[22px]": 1,
  },
  "routes/chat/ChatLoadingShell.styles.ts": { "mb-[18px]": 1, "mb-[10px]": 1 },
  "routes/chat/ChatRightRail.styles.ts": { "py-[18px]": 2 },
  "routes/chat/ChatSessionBrowser.styles.ts": { "px-[13px]": 1 },
  "routes/shared/ProgressiveRegionSkeleton.tsx": { "mb-[18px]": 1 },
};

function collectSourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = resolve(dir, entry.name);
    if (entry.isDirectory()) {
      return entry.name === "node_modules" ? [] : collectSourceFiles(full);
    }
    if (!/\.(ts|tsx)$/.test(entry.name) || /\.test\./.test(entry.name)) {
      return [];
    }
    return [full];
  });
}

function spacingGrowth(file: string, source: string): string[] {
  const counts: Record<string, number> = {};
  for (const [token] of source.matchAll(LITERAL_SPACING)) counts[token] = (counts[token] ?? 0) + 1;
  return Object.entries(counts)
    .filter(([token, count]) => count > (SPACING_DEBT[file]?.[token] ?? 0))
    .map(([token, count]) => `${file}: ${token} (${count} > ${SPACING_DEBT[file]?.[token] ?? 0})`);
}

describe("P0 style contract", () => {
  const files = collectSourceFiles(srcRoot);
  const countMatches = (pattern: RegExp) => files.reduce(
    (total, file) => total + [...readFileSync(file, "utf8").matchAll(pattern)].length, 0,
  );
  it("keeps fixedRadius at or below the frozen baseline", () => {
    expect(countMatches(FIXED_RADIUS)).toBeLessThanOrEqual(6);
  });
  it("keeps alphaUtility at zero", () => {
    expect(countMatches(ALPHA_UTILITY)).toBe(0);
  });
  it("does not grow literal spacing debt in any file or token", () => {
    const offenders = files.flatMap((file) => spacingGrowth(
      relative(srcRoot, file).replace(/\\/g, "/"), readFileSync(file, "utf8"),
    ));
    expect(offenders).toEqual([]);
  });
  it("rejects new spacing in a new file, new values and additional occurrences", () => {
    expect(spacingGrowth("new.tsx", "py-[7px]")).toHaveLength(1);
    expect(spacingGrowth("routes/AgentConversationDirectory.styles.ts", "py-[8px]")).toHaveLength(1);
    expect(spacingGrowth("routes/AgentConversationDirectory.styles.ts", "py-[7px] py-[7px]")).toHaveLength(1);
    expect(spacingGrowth("routes/AgentConversationDirectory.styles.ts", "py-[7px]")).toEqual([]);
    expect(spacingGrowth("routes/AgentConversationDirectory.styles.ts", "py-2")).toEqual([]);
  });
});
