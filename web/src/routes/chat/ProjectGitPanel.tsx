import { VRouteLinkButton } from "../../components/vui";
import { ChatChangeRail } from "./ChatChangeRail";
import { useChatGitRail } from "./useChatGitRail";
import { useChatChangePreview } from "./useChatChangePreview";
import styles from "./ProjectGitPanel.styles";

export function ProjectGitPanel({ lang }: { lang: "zh" | "en" }) {
  const rail = useChatGitRail(true);
  const preview = useChatChangePreview(rail.selectedPath);
  return <div className={styles.root}>
    <ChatChangeRail embedded className={styles.content} lang={lang} title={rail.branch ? `${lang === "zh" ? "仓库" : "Repository"} · ${rail.branch}` : lang === "zh" ? "仓库变更" : "Repository changes"} emptyLabel={lang === "zh" ? "工作区干净" : "Worktree is clean"} pending={rail.pending} unavailableLabel={rail.unavailable ? rail.errorText || (lang === "zh" ? "暂时无法读取仓库" : "Repository unavailable") : ""} paths={rail.paths} selectedPath={rail.selectedPath} changedPaths={new Set(rail.paths)} detailByPath={rail.detailByPath} diff={preview.diff} diffLoading={preview.diffLoading} hasDiff={preview.hasDiff} file={preview.file} fileLoading={preview.fileLoading} fileError={preview.fileError instanceof Error ? preview.fileError.message : ""} sourceLabel={lang === "zh" ? "工作区与 HEAD" : "Worktree vs HEAD"} onSelect={rail.selectPath} />
    <div className={styles.footer}><VRouteLinkButton to="/git" variant="ghost" density="compact">{lang === "zh" ? "提交记录、分支与同步" : "History, branches and sync"}</VRouteLinkButton></div>
  </div>;
}
