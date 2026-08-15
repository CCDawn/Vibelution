import { readFileSync, writeFileSync } from "node:fs";

for (const path of [
  "src/routes/TeamSourceCollectionScreeningWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionConversationWorkspacePanel.tsx",
  "src/routes/TeamKnowledgeCollectionCompletionFlowPanel.tsx",
  "src/routes/TeamSourceCollectionExtractionRecoveryWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionCandidateWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionGraphWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionMemoryWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionSelectedSourceWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionControlsWorkspacePanel.tsx",
  "src/routes/TeamSourceCollectionActiveStageWorkspacePanel.tsx",
]) {
  let t = readFileSync(path, "utf8");
  t = t.replace(/\.(map|find|filter|some|every)\(\(([a-zA-Z_][a-zA-Z0-9_]*)\) =>/g, ".$1(($2: any) =>");
  // multiline find/map callbacks
  t = t.replace(/\.(map|find|filter|some|every)\(\n\s*\(([a-zA-Z_][a-zA-Z0-9_]*)\) =>/g, ".$1(\n      ($2: any) =>");
  writeFileSync(path, t);
  console.log("fixed", path);
}
