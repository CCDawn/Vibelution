/**
 * Persistent three-stage rail for research projects.
 * One-click stage switch; unlocked stages only.
 */
import { VButton } from "../../components/vui";
import { RESEARCH_STAGE_TERMS } from "./research-workflow/researchTerminology";
import type { ResearchStageWorkspaceView } from "./researchWorkspaceModel";
import type { ResearchStageUnlock } from "./researchPrimaryActionModel";

export type ResearchStageNavProps = {
  lang: "zh" | "en";
  current: ResearchStageWorkspaceView | "overview";
  unlock: ResearchStageUnlock;
  onSelect: (view: ResearchStageWorkspaceView) => void;
  onOverview?: () => void;
  className?: string;
};

const STAGES: Array<{
  id: ResearchStageWorkspaceView;
  zh: string;
  en: string;
}> = [
  { id: "knowledge_collection", zh: RESEARCH_STAGE_TERMS.knowledge_collection.zh, en: RESEARCH_STAGE_TERMS.knowledge_collection.en },
  { id: "experiment", zh: "实验设计", en: "Experiment" },
  { id: "iteration", zh: "执行迭代", en: "Iteration" },
];

export function ResearchStageNav({
  lang,
  current,
  unlock,
  onSelect,
  onOverview,
  className = "",
}: ResearchStageNavProps) {
  return (
    <nav
      className={["flex min-w-0 flex-wrap items-center gap-1.5", className].filter(Boolean).join(" ")}
      data-testid="research-stage-nav"
      data-vui="research-stage-nav"
      data-current={current}
      aria-label={lang === "zh" ? "科研阶段" : "Research stages"}
    >
      {onOverview ? (
        <VButton
          type="button"
          density="compact"
          variant={current === "overview" ? "primary" : "secondary"}
          data-testid="research-stage-nav-overview"
          isDisabled={current === "overview"}
          onPress={onOverview}
        >
          {lang === "zh" ? "总览" : "Overview"}
        </VButton>
      ) : null}
      {STAGES.map((stage, index) => {
        const unlocked = unlock[stage.id];
        const isCurrent = current === stage.id;
        const label = lang === "zh" ? stage.zh : stage.en;
        return (
          <div key={stage.id} className="inline-flex items-center gap-1.5">
            {index > 0 || onOverview ? (
              <span className="text-[var(--fg-tertiary)]" aria-hidden="true">
                ·
              </span>
            ) : null}
            <VButton
              type="button"
              density="compact"
              variant={isCurrent ? "primary" : "secondary"}
              data-testid={`research-stage-nav-${stage.id}`}
              data-current={isCurrent ? "true" : "false"}
              data-unlocked={unlocked ? "true" : "false"}
              isDisabled={!unlocked || isCurrent}
              title={
                unlocked
                  ? label
                  : (lang === "zh" ? `尚未解锁：${label}` : `Locked: ${label}`)
              }
              onPress={() => {
                if (!unlocked || isCurrent) return;
                onSelect(stage.id);
              }}
            >
              {label}
            </VButton>
          </div>
        );
      })}
    </nav>
  );
}
