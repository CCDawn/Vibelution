import { useEffect, useMemo, useState } from "react";

import {
  VCommandPalette,
  type VCommandPaletteItem,
} from "../../../components/vui";
import type { ResearchWorkflowLaunchOption } from "../../../api/researchWorkflow";
import type { HypothesisFirstNextAction } from "./hypothesisFirstNextAction";

/**
 * Ctrl+K command palette for the research workspace (Linear/VS Code pattern).
 * Owns palette state and item composition so the workspace shell stays
 * composition-only; navigation consequences run through the callbacks the
 * workspace already owns (selectExperiment / openPanel / replaceParams).
 */
export function ResearchCommandPalette(props: {
  questions: readonly ResearchWorkflowLaunchOption[];
  nextAction: HypothesisFirstNextAction;
  /** A hypothesis-first chain may be active without a formal run id. */
  workflowActive: boolean;
  onSelectExperiment: (questionId: string) => void;
  onOpenPanel: (panel: "team" | "progress") => void;
  onNavigateNode: (nodeId: string) => void;
}) {
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
        event.preventDefault();
        setOpen((current) => !current);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, []);

  const items = useMemo<VCommandPaletteItem[]>(() => {
    const commands: VCommandPaletteItem[] = [];
    if (props.workflowActive && props.nextAction.targetNodeId) {
      commands.push({
        id: "cmd:current-task",
        group: "命令",
        label: props.nextAction.navigationLabel || "前往当前任务",
        detail: props.nextAction.commandLabel || props.nextAction.statusMessage || undefined,
        onRun: () => props.onNavigateNode(props.nextAction.targetNodeId || ""),
      });
    }
    commands.push({
      id: "cmd:members-discussion",
      group: "命令",
      label: "打开成员与讨论",
      onRun: () => props.onOpenPanel("team"),
    });
    commands.push({
      id: "cmd:question-progress",
      group: "命令",
      label: "查看题目进度",
      onRun: () => props.onOpenPanel("progress"),
    });
    const questions: VCommandPaletteItem[] = props.questions.map((question) => ({
      id: `question:${question.questionId}`,
      group: "题目",
      label: question.questionId,
      detail: question.title,
      keywords: `${question.questionId} ${question.title}`,
      onRun: () => props.onSelectExperiment(question.questionId),
    }));
    return [...commands, ...questions];
  }, [props]);

  return (
    <VCommandPalette
      open={open}
      onOpenChange={setOpen}
      items={items}
      labels={{
        searchPlaceholder: "搜索题目或命令…",
        emptyTitle: "没有匹配项",
        hint: "↑↓ 选择 · Enter 执行 · Esc 关闭",
      }}
    />
  );
}
