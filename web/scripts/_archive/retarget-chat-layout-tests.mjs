/**
 * Wave 8C: retarget Chat layout tests after panel style extraction.
 * - Merge panel style maps into routeStyles alias where tests read class strings
 * - Accept styles.X | routeStyles.X in source-string contracts
 *
 * Usage (from web/): node scripts/retarget-chat-layout-tests.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

function patchFile(path, fn) {
  const before = readFileSync(path, "utf8");
  const after = fn(before);
  if (after !== before) {
    writeFileSync(path, after);
    console.log("patched", path);
  } else {
    console.log("unchanged", path);
  }
}

// --- CacheDetailDialog.layout.test.ts ---
patchFile("src/routes/chat/CacheDetailDialog.layout.test.ts", (src) => {
  let out = src.replace(
    /import routeStyles from "\.\.\/ChatCodingRoute\.styles";/,
    `import routeStyles from "../ChatCodingRoute.styles";\nimport cacheDetailStyles from "./CacheDetailDialog.styles";`,
  );
  // donut/cache keys live on cacheDetailStyles; segment tones may stay on route
  const cacheKeys = [
    "cacheDetailDonutShell",
    "cacheDetailDonutSvg",
    "cacheDetailDonutCenter",
    "cacheDonutTrack",
    "cacheDonutSegment",
    "cacheDetailBody",
    "cacheDetailDialog",
    "cacheDetailOverlay",
    "cacheDetailSummaryGrid",
    "cacheDetailCalibrationNote",
    "cacheDetailDonutLegend",
    "cacheDetailSegmentSource",
    "cacheDetailSegmentList",
    "cacheDetailBoundary",
    "cacheDetailBoundaryTrack",
    "cacheDetailBoundaryHit",
    "cacheDetailBoundaryMiss",
    "cacheDetailBoundaryUnknown",
    "cacheDetailBoundaryLabels",
    "cacheDetailCloseButton",
    "cacheDetailDonutPanel",
    "cacheDetailHeader",
    "cacheDetailTitleRow",
  ];
  for (const k of cacheKeys) {
    out = out.replaceAll(`routeStyles.${k}`, `cacheDetailStyles.${k}`);
  }
  // donutSegmentToneKeys array access routeStyles[key] -> prefer cache then route
  if (out.includes("donutSegmentToneKeys") && !out.includes("resolveDonutTone")) {
    out = out.replace(
      "describe(\"CacheDetailDialog donut layout contract\"",
      `function resolveDonutTone(key: string): string {
  return (cacheDetailStyles as Record<string, string>)[key]
    ?? (routeStyles as Record<string, string>)[key]
    ?? "";
}

describe("CacheDetailDialog donut layout contract"`,
    );
    out = out.replace(/routeStyles\[key\]/g, "resolveDonutTone(key)");
    out = out.replace(/routeStyles\[toneKey\]/g, "resolveDonutTone(toneKey)");
  }
  return out;
});

// --- runModeChip ---
patchFile("src/routes/ChatCodingRoute.runModeChip.test.ts", (src) =>
  src.replace(
    /import styles from "\.\/ChatCodingRoute\.styles";/,
    `import styles from "./chat/ChatStatusRail.styles";`,
  ),
);

// --- LeftStatus ---
patchFile("src/routes/ChatCodingLeftStatus.layout.test.ts", (src) => {
  let out = src.replace(
    /import styles from "\.\/ChatCodingRoute\.styles";/,
    `import routeStyles from "./ChatCodingRoute.styles";
import statusRailStyles from "./chat/ChatStatusRail.styles";
import tokenCoreStyles from "./chat/TokenCoreStatusPanel.styles";

const styles = {
  ...routeStyles,
  ...statusRailStyles,
  ...tokenCoreStyles,
} as Record<string, string>;`,
  );
  return out;
});

// --- Main ChatCodingRoute.layout.test.ts ---
patchFile("src/routes/ChatCodingRoute.layout.test.ts", (src) => {
  let out = src;

  // Add panel style imports after routeStyles import
  if (!out.includes("ChatStatusRail.styles")) {
    out = out.replace(
      /import routeStyles from "\.\/ChatCodingRoute\.styles";/,
      `import routeStylesBase from "./ChatCodingRoute.styles";
import cacheDetailStyles from "./chat/CacheDetailDialog.styles";
import conversationIndexRailStyles from "./chat/ChatConversationIndexRail.styles";
import chatStatusRailStyles from "./chat/ChatStatusRail.styles";
import tokenCoreStatusPanelStyles from "./chat/TokenCoreStatusPanel.styles";

/** Wave 8C: layout contracts resolve class strings across route shell + extracted panel maps. */
const routeStyles = {
  ...routeStylesBase,
  ...cacheDetailStyles,
  ...conversationIndexRailStyles,
  ...chatStatusRailStyles,
  ...tokenCoreStatusPanelStyles,
} as Record<string, string>;`,
    );
  }

  // Source-string contracts: accept styles.X or routeStyles.X (dual-import panels)
  // Replace expect(...).toContain("styles.KEY") when KEY is a known shared/routeStyles ref
  // Broader: for combined sources that include panels with dual import
  const dualKeys = [
    "agentRoleTag",
    "agentModelTag",
    "agentModelLine",
    "railSectionHeading",
    "sectionEyebrowRow",
    "sectionHeader",
    "sectionIdentity",
    "sectionTitle",
    "blockEyebrow",
    "contextLineCompact",
    "panelNotice",
    "resourceSplit",
    "resourceMetric",
    "oneLineValue",
    "mentalStateBadge",
    "agentOptionAvatar",
    "leftBlock",
    "groupMemberCopy",
  ];

  for (const k of dualKeys) {
    const needle = `toContain("styles.${k}")`;
    const replacement = `toMatch(/styles\\.${k}|routeStyles\\.${k}/)`;
    out = out.replaceAll(needle, replacement);
    const needle2 = `toContain('styles.${k}')`;
    out = out.replaceAll(needle2, replacement);
  }

  // not.toContain styles.X for extracted keys should still pass if removed from route source
  return out;
});

console.log("done");
