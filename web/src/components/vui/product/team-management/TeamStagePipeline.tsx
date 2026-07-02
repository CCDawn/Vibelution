import { type ReactNode } from "react";

export type TeamStagePipelineProps = {
  id?: string;
  ariaLabel?: string;
  children: ReactNode;
};

/** A responsive stage pipeline sized for the current four-stage source flow. */
export function TeamStagePipeline({ id, ariaLabel, children }: TeamStagePipelineProps) {
  return (
    <section
      id={id}
      data-vui-product="team-stage-pipeline"
      aria-label={ariaLabel}
      className="grid grid-cols-[repeat(auto-fit,minmax(220px,1fr))] items-stretch gap-2 min-w-0 max-[560px]:grid-cols-[1fr]"
    >
      {children}
    </section>
  );
}
