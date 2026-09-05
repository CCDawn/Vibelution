import { useCallback, useRef, useState } from "react";

import { fetchHypothesisFirstFocusNode } from "./hypothesisFirstFocus";
import {
  resolveExperimentSwitch,
  type ExperimentSwitchOption,
} from "./researchExperimentSwitchModel";

type ReplaceParams = (patch: Record<string, string | null | undefined>) => void;

function focusErrorMessage(reason: unknown): string {
  const detail = reason instanceof Error ? reason.message : String(reason);
  return `实验焦点读取失败：${detail}`;
}

export function useResearchExperimentSwitch(options: {
  teamId: string;
  experiments: readonly ExperimentSwitchOption[];
  replaceParams: ReplaceParams;
}) {
  const [error, setError] = useState<string | null>(null);
  const requestSeqRef = useRef(0);

  const selectExperiment = useCallback((questionId: string) => {
    const patch = resolveExperimentSwitch(options.experiments, questionId);
    if (!patch) return;
    const requestSeq = ++requestSeqRef.current;
    setError(null);
    if (patch.panel !== "node") {
      options.replaceParams(patch);
      return;
    }
    void fetchHypothesisFirstFocusNode(
      options.teamId,
      patch.questionId,
      patch.runId,
    ).then((node) => {
      if (requestSeq !== requestSeqRef.current) return;
      options.replaceParams({ ...patch, node });
    }).catch((reason: unknown) => {
      if (requestSeq !== requestSeqRef.current) return;
      setError(focusErrorMessage(reason));
      options.replaceParams(patch);
    });
  }, [options.experiments, options.replaceParams, options.teamId]);

  return { error, selectExperiment };
}
