import { ChatRightRail, type ChatRightRailReview } from "../routes/chat/ChatRightRail";
import { collapseProjectUtilityRail, getProjectUtilityRail, setProjectUtilityModel, useProjectUtilityRail } from "./projectUtilityRail";
import styles from "./ShellProjectUtilities.styles";

const emptyReview: ChatRightRailReview = { sessionTitle: "", sessionEmptyLabel: "", sessionPaths: [], sessionSelectedPath: null, sessionChangedPaths: new Set(), gitTitle: "", gitEmptyLabel: "", gitPending: false, gitPendingLabel: "", gitUnavailableLabel: "", gitPaths: [], gitSelectedPath: null, diff: undefined, diffLoading: false, hasDiff: false, file: null, fileLoading: false, fileError: "", sourceLabel: "", onSelectSessionFile: () => {}, onSelectGitFile: () => {} };
/** Same rail renderer; only project tools are enabled outside an ordinary conversation. */
export function ShellProjectUtilities({ lang, onOpenSession }: { lang: "zh" | "en"; onOpenSession: (id: string) => void }) {
  const project = useProjectUtilityRail();
  return <ChatRightRail id="shell-project-utilities" className={styles.rail} lang={lang} sessionId="" model={project.model} onModelChange={(update) => { const previous = getProjectUtilityRail().model; const next = typeof update === "function" ? update(previous) : update; setProjectUtilityModel(next, true); }} onCollapse={collapseProjectUtilityRail} review={emptyReview} devtools={null} terminalRun={null} terminalMountedInCenter={false} onOpenFile={() => {}} onOpenSession={onOpenSession} />;
}
