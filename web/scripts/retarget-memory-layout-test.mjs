/**
 * Wave 8A: retarget expect(styles.KEY) after MemoryRoute.styles prune.
 * Does not touch string literals that assert panel sources contain "styles.foo".
 */
import fs from "node:fs";
import path from "node:path";

const testPath = "web/src/routes/MemoryRoute.layout.test.ts";
const shellPath = "web/src/routes/MemoryRoute.styles.ts";
const routesDir = "web/src/routes";

const shellSrc = fs.readFileSync(shellPath, "utf8");
const shellKeys = new Set([...shellSrc.matchAll(/^\s{2}([a-zA-Z][a-zA-Z0-9_]*):/gm)].map((m) => m[1]));

const specials = {
  MemoryAgentMemoryPanel: "agentMemoryPanelStyles",
  MemoryCleanupPanel: "cleanupPanelStyles",
  MemoryDetailPanel: "detailPanelStyles",
  MemoryEffectivePanel: "effectivePanelStyles",
  MemoryGraphNodeInspectorPanel: "graphNodeInspectorPanelStyles",
  MemoryGraphViewPanel: "graphViewPanelStyles",
  MemoryItemListPanel: "itemListPanelStyles",
  MemoryKnowledgeModeTabs: "knowledgeModeTabsStyles",
  MemoryKnowledgePermissionsPanel: "knowledgePermissionsPanelStyles",
  MemoryKnowledgePipelinePanel: "knowledgePipelinePanelStyles",
  MemoryKnowledgeReviewPanel: "knowledgeReviewPanelStyles",
  MemoryKnowledgeItemRatingCard: "knowledgeItemRatingCardStyles",
  MemoryKnowledgeUsageContractPanel: "knowledgeUsageContractPanelStyles",
  MemoryKnowledgeSourceGovernancePanel: "knowledgeSourceGovernancePanelStyles",
  MemoryManagePanel: "managePanelStyles",
  MemoryManagementEditorActionPreviewPanel: "managementActionPreviewPanelStyles",
  MemoryMatrixPanel: "matrixPanelStyles",
  MemoryOverviewPanel: "overviewPanelStyles",
  MemoryProjectMemoryQueuePanel: "projectMemoryQueuePanelStyles",
  MemorySelectedConfigPanel: "selectedConfigPanelStyles",
  MemorySourceAndItemPanels: "sourceAndItemPanelStyles",
  MemoryUserContentPanel: "userContentPanelStyles",
  MemoryWarningStrip: "warningStripStyles",
  MemoryReviewQueuePanel: "reviewQueuePanelStyles",
  MemoryKnowledgeRagPanel: "knowledgeRagPanelStyles",
  MemoryKnowledgeStewardPanel: "knowledgeStewardPanelStyles",
  MemoryGraphCanvas: "graphCanvasStyles",
};

const keyOwners = new Map();
for (const file of fs.readdirSync(routesDir)) {
  if (!/^Memory.*\.styles\.ts$/.test(file) || file === "MemoryRoute.styles.ts") continue;
  const base = file.replace(/\.styles\.ts$/, "");
  const varName = specials[base];
  if (!varName) continue;
  const src = fs.readFileSync(path.join(routesDir, file), "utf8");
  for (const m of src.matchAll(/^\s{2}([a-zA-Z][a-zA-Z0-9_]*):/gm)) {
    if (!keyOwners.has(m[1])) keyOwners.set(m[1], varName);
  }
}

let out = fs.readFileSync(testPath, "utf8");

const ensureImports = [
  'import agentMemoryPanelStyles from "./MemoryAgentMemoryPanel.styles";',
  'import cleanupPanelStyles from "./MemoryCleanupPanel.styles";',
  'import projectMemoryQueuePanelStyles from "./MemoryProjectMemoryQueuePanel.styles";',
  'import knowledgeSourceGovernancePanelStyles from "./MemoryKnowledgeSourceGovernancePanel.styles";',
  'import reviewQueuePanelStyles from "./MemoryReviewQueuePanel.styles";',
  'import knowledgeRagPanelStyles from "./MemoryKnowledgeRagPanel.styles";',
  'import knowledgeStewardPanelStyles from "./MemoryKnowledgeStewardPanel.styles";',
  'import graphCanvasStyles from "./MemoryGraphCanvas.styles";',
];
for (const line of ensureImports) {
  if (!out.includes(line)) {
    out = out.replace(
      'import styles from "./MemoryRoute.styles";',
      `${line}\nimport styles from "./MemoryRoute.styles";`,
    );
  }
}

const cssBlock = `const memoryCssSource = [
  stylesModuleSource,
  ...[
    styles,
    agentMemoryPanelStyles,
    cleanupPanelStyles,
    detailPanelStyles,
    effectivePanelStyles,
    graphNodeInspectorPanelStyles,
    graphViewPanelStyles,
    graphCanvasStyles,
    knowledgeStewardPanelStyles,
    knowledgeRagPanelStyles,
    itemListPanelStyles,
    knowledgeModeTabsStyles,
    knowledgePermissionsPanelStyles,
    knowledgePipelinePanelStyles,
    knowledgeReviewPanelStyles,
    knowledgeItemRatingCardStyles,
    knowledgeUsageContractPanelStyles,
    knowledgeSourceGovernancePanelStyles,
    managePanelStyles,
    managementActionPreviewPanelStyles,
    matrixPanelStyles,
    overviewPanelStyles,
    projectMemoryQueuePanelStyles,
    reviewQueuePanelStyles,
    selectedConfigPanelStyles,
    sourceAndItemPanelStyles,
    userContentPanelStyles,
    warningStripStyles,
  ].flatMap((map) => [
    ...Object.keys(map).map((key) => \`.\${key}\`),
    ...Object.values(map),
  ]),
].join("\\n");`;

out = out.replace(/const memoryCssSource = \[[\s\S]*?\]\.join\("\\n"\);/, cssBlock);

// Retarget styles.KEY property access only outside string literals.
// Simple tokenizer: split by quotes and only rewrite odd/even segments carefully.
function retargetOutsideStrings(source) {
  const parts = [];
  let i = 0;
  while (i < source.length) {
    const ch = source[i];
    if (ch === '"' || ch === "'" || ch === "`") {
      const quote = ch;
      let j = i + 1;
      while (j < source.length) {
        if (source[j] === "\\") {
          j += 2;
          continue;
        }
        if (source[j] === quote) {
          j += 1;
          break;
        }
        j += 1;
      }
      parts.push({ code: false, text: source.slice(i, j) });
      i = j;
      continue;
    }
    let j = i + 1;
    while (j < source.length && source[j] !== '"' && source[j] !== "'" && source[j] !== "`") j += 1;
    parts.push({ code: true, text: source.slice(i, j) });
    i = j;
  }
  return parts
    .map((p) => {
      if (!p.code) return p.text;
      return p.text.replace(/\bstyles\.([a-zA-Z0-9_]+)\b/g, (full, key) => {
        if (shellKeys.has(key)) return full;
        const owner = keyOwners.get(key);
        if (!owner) {
          console.warn("no owner for", key);
          return full;
        }
        return `${owner}.${key}`;
      });
    })
    .join("");
}

out = retargetOutsideStrings(out);

fs.writeFileSync(testPath, out);

const still = [
  ...new Set(
    [...out.matchAll(/\bstyles\.([a-zA-Z0-9_]+)\b/g)]
      .map((m) => m[1])
      .filter((k) => !shellKeys.has(k)),
  ),
];
// filter false positives inside strings? already retargeted outside strings only
console.log(JSON.stringify({ shellKeys: shellKeys.size, stillOutsideStrings: still }, null, 2));
