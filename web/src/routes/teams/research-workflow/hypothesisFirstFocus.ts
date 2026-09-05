/** Select the current canvas task from the V2 authority after a scope change. */
import { fetchHypothesisFirstStateV2 } from "../../../api/hypothesisFirst";
import { HYPOTHESIS_FIRST_GENERATION_NODE_ID } from "./hypothesisFirstCanvasRegion";
import { focusNodeFromNextAction } from "./hypothesisFirstNextAction";
import { resolveHypothesisFirstNextActionFromV2 } from "./hypothesisFirstStateV2Adapter";

export async function fetchHypothesisFirstFocusNode(teamId: string, questionId: string, runId = ""): Promise<string> {
  const team = teamId.trim();
  const question = questionId.trim();
  if (!team || !question) return HYPOTHESIS_FIRST_GENERATION_NODE_ID;
  const state = await fetchHypothesisFirstStateV2(team, question, { runId: runId.trim() });
  const fatal = state.problems.find((problem) => problem.severity === "fatal");
  if (fatal) throw new Error(fatal.message || fatal.code);
  return focusNodeFromNextAction(resolveHypothesisFirstNextActionFromV2(state));
}
