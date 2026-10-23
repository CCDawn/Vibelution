/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { Team } from "../../../api/types";
import type { Flow } from "./workflowModel";
import { GenericWorkflowWorkspace } from "./GenericWorkflowWorkspace";
import { createWorkflow } from "./workflowTemplates";

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), shell: vi.fn(), dialog: vi.fn() }));
vi.mock("./useWorkflowWorkspace", () => ({ useWorkflowWorkspace: mocks.workspace }));
vi.mock("./WorkbenchShell", () => ({ WorkbenchShell: mocks.shell }));
vi.mock("./WorkflowArtifactDialog", () => ({ WorkflowArtifactDialog: () => null }));
vi.mock("../../../components/vui", () => ({
  VButton: () => null, VCheckbox: () => null, VConfirmDialog: () => null, VDialog: mocks.dialog,
  VInput: () => null, VRouteLinkButton: () => null, VSelect: () => null, VTextarea: () => null,
}));
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

it.each(["team", "flow"])("closes an old launch snapshot when switching %s", async scope => {
  let flow: Flow = { ...createWorkflow("A", "blank", []), revision: 1 };
  const start = vi.fn();
  mocks.workspace.mockImplementation(() => ({ flow, flows: [flow], runs: [], dirty: false,
    save: async () => flow, start, selectFlow: vi.fn(), editFlow: vi.fn(), command: vi.fn() }));
  mocks.shell.mockImplementation(() => null); mocks.dialog.mockImplementation(() => null);
  const root = createRoot(document.createElement("div"));
  const render = (teamId: string) => root.render(<GenericWorkflowWorkspace team={{ teamId, members: [] } as unknown as Team}
    teams={[]} onTeam={vi.fn()} onDiscussion={vi.fn()} onHistory={vi.fn()} />);
  const launchDialog = () => mocks.dialog.mock.calls.filter(([props]) => props.title === "开始一次运行").at(-1)![0];
  try {
    await act(async () => render("team-a"));
    await act(async () => { await mocks.shell.mock.calls.at(-1)![0].onStart(); });
    expect(launchDialog().open).toBe(true);
    if (scope === "flow") flow = { ...flow, id: "flow-b" };
    await act(async () => render(scope === "team" ? "team-b" : "team-a"));
    expect(launchDialog().open).toBe(false);
    expect(start).not.toHaveBeenCalled();
  } finally { act(() => root.unmount()); }
});
