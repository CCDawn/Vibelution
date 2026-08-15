/**
 * Wire useAgentConfigDraftMutations into AgentsRoute (F3-A2).
 * Usage from web/: node scripts/wire-agent-config-draft-mutations.mjs
 */
import { readFileSync, writeFileSync } from "node:fs";

const routePath = "src/routes/AgentsRoute.tsx";
let src = readFileSync(routePath, "utf8");

const start = src.indexOf("  const saveAgentConfigDraftMutation = useMutation({");
const end = src.indexOf("  const updatePersonaMutation = useMutation({");
if (start < 0 || end <= start) {
  console.error("markers missing", start, end);
  process.exit(1);
}

const hook = `  const {
    saveAgentConfigDraftMutation,
    discardAgentConfigDraftMutation,
    updateAgentMutation,
    promoteAgentModelMutation,
  } = useAgentConfigDraftMutations({
    lang,
    setNotice,
    chatWorkspaceCache,
    setConfigDraft,
    draftSyncSourceRef,
    getWorkspace: () => workspace,
    draftFromAgent,
    draftSyncSourceFromAgent,
    normalizeAgentLlmBindings,
    contextCompressionPolicyFromDraft,
    agentMetadataWithReasoningEffort,
    agentLabel,
    updatedAgentWorkspaceCache,
  });

`;

src = src.slice(0, start) + hook + src.slice(end);

if (!src.includes('from "./agents/useAgentConfigDraftMutations"')) {
  src = src.replace(
    'import { useShellI18n } from "../i18n/useShellI18n";',
    'import { useShellI18n } from "../i18n/useShellI18n";\nimport { useAgentConfigDraftMutations } from "./agents/useAgentConfigDraftMutations";',
  );
}

writeFileSync(routePath, src);
console.log("wired config draft mutations");
