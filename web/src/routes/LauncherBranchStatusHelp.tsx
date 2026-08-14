import type { ReactNode } from "react";

import type { LauncherBranchInstance } from "../api/launcher";
import { VTooltip } from "../components/vui";
import type { InstanceRuntimeState } from "./LauncherBranchInstancesPanel.model";
import {
  cleanupRecommendation,
  gitStatusExplanation,
  runtimeStatusExplanation,
} from "./LauncherBranchStatusHelp.model";

type LauncherBranchStatusHelpProps = {
  children: ReactNode;
  item: LauncherBranchInstance;
  state: InstanceRuntimeState;
  isZh: boolean;
  kind: "runtime" | "git";
};

export function LauncherBranchStatusHelp({
  children,
  item,
  state,
  isZh,
  kind,
}: LauncherBranchStatusHelpProps) {
  const explanation = kind === "runtime"
    ? runtimeStatusExplanation(state, isZh)
    : gitStatusExplanation(item, isZh);
  const recommendation = cleanupRecommendation(item, state, isZh);
  const content = `${explanation} ${recommendation.label}${isZh ? "：" : ": "}${recommendation.reason}`;
  const tone = recommendation.level === "avoid"
    ? "danger"
    : recommendation.level === "review"
      ? "warning"
      : "neutral";

  return (
    <VTooltip content={content} tone={tone} width="wide">
      <span
        className="inline-flex cursor-help rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-[var(--focus-ring)]"
        tabIndex={0}
      >
        {children}
      </span>
    </VTooltip>
  );
}
