import { isEditableWorkflow, type Flow, type InputField, type StepKind } from "./workflowModel";

// Presentation hints only. Never persist names, instructions, values, identities or pane dimensions.
const KEY = "vibelution.team-flow-loading-shapes.v1";
type Shape = { steps: StepKind[]; fields: InputField["kind"][] };
type Entry = { at: number; flows: Shape[] };
const stepKinds = ["input", "agent", "human", "output"];
const fieldKinds = ["text", "paragraph", "select"];
const MAX_AGE = 30 * 24 * 60 * 60 * 1000;

function valid(value: unknown): value is Entry {
  if (!value || typeof value !== "object") return false;
  const entry = value as Entry;
  return Number.isFinite(entry.at) && entry.at <= Date.now() && Date.now() - entry.at < MAX_AGE
    && Array.isArray(entry.flows) && entry.flows.length <= 100
    && entry.flows.every(flow => flow && Array.isArray(flow.steps) && flow.steps.length > 0 && flow.steps.length <= 100
      && flow.steps.every(kind => stepKinds.includes(kind)) && Array.isArray(flow.fields) && flow.fields.length <= 100
      && flow.fields.every(kind => fieldKinds.includes(kind)));
}

export function readWorkflowLoadingShape(teamId: string): Flow[] | undefined {
  if (!teamId) return;
  try {
    const raw = window.localStorage.getItem(KEY);
    if (!raw || raw.length > 200_000) return;
    const entries: unknown = JSON.parse(raw);
    if (!entries || typeof entries !== "object" || !Object.hasOwn(entries, teamId)) return;
    const entry: unknown = (entries as Record<string, unknown>)[teamId];
    if (!valid(entry)) return;
    return materialize(entry.flows);
  } catch { /* Storage can be disabled; server data remains authoritative. */ }
}

function materialize(shapes: Shape[]): Flow[] {
  return shapes.map((shape, index) => ({
      id: `loading-flow-${index}`, name: "正在读取流程", description: "", revision: 0, updatedAt: "",
      steps: shape.steps.map((kind, step) => ({ id: `loading-step-${step}`, kind, label: "正在读取步骤", owner: "", instruction: "正在读取执行要求" })),
      fields: shape.fields.map((kind, field) => ({ id: `loading-field-${field}`, kind, label: "", required: false, options: [] })),
    }));
}

/** Unknown is not confirmed empty: reserve the editor frame until the server classifies it. */
export function unknownWorkflowLoadingShape(): Flow[] {
  return materialize([{ steps: ["input", "agent", "agent", "human", "output"], fields: ["paragraph", "select"] }]);
}

export function rememberWorkflowLoadingShape(teamId: string, definitions: Flow[]) {
  if (!teamId) return;
  try {
    const flows = definitions.filter(isEditableWorkflow).map(flow => ({ steps: flow.steps.map(step => step.kind), fields: flow.fields.map(field => field.kind) }));
    const entry = { at: Date.now(), flows };
    if (!valid(entry)) { window.localStorage.removeItem(KEY); return; }
    const raw = window.localStorage.getItem(KEY);
    let previous: unknown = {};
    try { previous = raw && raw.length < 200_000 ? JSON.parse(raw) : {}; } catch { /* Replace corrupt hints after a successful read. */ }
    const entries = previous && typeof previous === "object" ? Object.entries(previous).filter(([id, value]) => id !== teamId && valid(value)).slice(-19) : [];
    const next = [...entries, [teamId, entry] as const];
    let encoded = JSON.stringify(Object.fromEntries(next));
    while (encoded.length > 200_000 && next.length > 1) {
      next.shift(); encoded = JSON.stringify(Object.fromEntries(next));
    }
    if (encoded.length <= 200_000) window.localStorage.setItem(KEY, encoded);
  } catch { /* A loading hint must never prevent reading or saving a workflow. */ }
}
