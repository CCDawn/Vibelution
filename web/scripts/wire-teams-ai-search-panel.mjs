import { readFileSync, writeFileSync } from "node:fs";

const path = "src/routes/TeamsRoute.tsx";
let src = readFileSync(path, "utf8");
const start = src.indexOf("  function renderAiSearchSourceScopePanel() {");
const end = src.indexOf("  function renderSourceCollectionRunSwitcher() {");
if (start < 0 || end < 0 || end <= start) {
  console.error("markers not found", start, end);
  process.exit(1);
}
const replacement = `  function renderAiSearchSourceScopePanel() {
    return (
      <TeamAiSearchWorkspacePanel
        lang={lang}
        scope={selectedTeam?.sourceScope ?? null}
        teamDetailPending={teamDetailQuery.isPending}
        runs={aiSearchRuns}
        runsPending={aiSearchRunsQuery.isPending}
        runsFetching={aiSearchRunsQuery.isFetching}
        visibleRunCount={aiSearchRunsQuery.data?.summary.visibleRunCount ?? aiSearchRuns.length}
        totalRunCount={aiSearchRunsQuery.data?.summary.runCount ?? aiSearchRuns.length}
        latestRun={latestAiSearchRun}
        topic={aiSearchRunTopic}
        onTopicChange={setAiSearchRunTopic}
        canStart={aiSearchRunCanStart}
        startPending={selectedTeamStartAiSearchPending}
        startErrorMessage={selectedTeamStartAiSearchError?.message ?? null}
        onStart={(payload) => startAiSearchRunMutation.mutate(payload)}
        teamId={selectedTeam?.teamId}
      />
    );
  }

`;
src = src.slice(0, start) + replacement + src.slice(end);
writeFileSync(path, src);
console.log("wired TeamAiSearchWorkspacePanel, removed", end - start, "chars");
