import { type ReactNode } from "react";

export type TeamStagePipelineProps = {
  id?: string;
  ariaLabel?: string;
  children: ReactNode;
};

/**
 * Faithful reproduction of `.sourceCollectionStageModules`:
 * a five-column stage pipeline (repeat(5, minmax(0, 1fr))) that collapses to
 * two columns on narrow viewports.
 */
export function TeamStagePipeline({ id, ariaLabel, children }: TeamStagePipelineProps) {
  return (
    <section
      id={id}
      data-vui-product="team-stage-pipeline"
      aria-label={ariaLabel}
      className="grid grid-cols-[repeat(5,minmax(0,1fr))] items-start gap-[5px] min-w-0 max-[1080px]:grid-cols-[repeat(2,minmax(0,1fr))] max-[560px]:grid-cols-[1fr]"
    >
      {children}
    </section>
  );
}
