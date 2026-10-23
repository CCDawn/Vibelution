/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { expect, it, vi } from "vitest";
import type { Team } from "../../../api/types";
import type { Flow } from "./workflowModel";
import { GenericWorkflowWorkspace } from "./GenericWorkflowWorkspace";
import { createWorkflow, workflowTemplatePreviews } from "./workflowTemplates";

const mocks = vi.hoisted(() => ({ workspace: vi.fn(), shell: vi.fn(), dialog: vi.fn() }));
vi.mock("./useWorkflowWorkspace", () => ({ useWorkflowWorkspace: mocks.workspace }));
vi.mock("./WorkbenchShell", () => ({ WorkbenchShell: mocks.shell }));
vi.mock("./WorkflowArtifactDialog", () => ({ WorkflowArtifactDialog: () => null }));
vi.mock("../../../components/vui", () => ({
  VButton: ({ children, onClick, isDisabled }: { children: React.ReactNode; onClick?: () => void; isDisabled?: boolean }) =>
    <button onClick={onClick} disabled={isDisabled}>{children}</button>,
  VCheckbox: () => null, VConfirmDialog: () => null, VDialog: mocks.dialog,
  VInput: ({ value, "aria-label": label }: { value: string; "aria-label": string }) => <input aria-label={label} value={value} readOnly/>,
  VRouteLinkButton: () => null,
  VSelect: ({ selectedKey, options, "aria-label": label }: { selectedKey: string; options: { id: string; label: string }[]; "aria-label": string }) =>
    <select aria-label={label} value={selectedKey} disabled>{options.map(option => <option key={option.id} value={option.id}>{option.label}</option>)}</select>,
  VTextarea: () => null,
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

it.each(workflowTemplatePreviews)("creates the selected $name template with real team members", async preview => {
  const addFlow = vi.fn();
  const team = { teamId: "real-team", members: [
    { agentId: "inactive", agentName: "不可用成员", agentStatus: "inactive" },
    { agentId: "researcher", agentName: "资料成员", agentStatus: "active" },
    { agentId: "reviewer", agentName: "复核成员", agentStatus: "active" },
    { agentId: "writer", agentName: "交付成员", agentStatus: "active" },
  ] } as unknown as Team;
  mocks.workspace.mockImplementation(() => ({ flows: [], runs: [], dirty: false, addFlow, editFlow: vi.fn() }));
  mocks.shell.mockImplementation(() => null);
  mocks.dialog.mockImplementation(({ open, title, children, footer }: { open: boolean; title: string; children: React.ReactNode; footer: React.ReactNode }) =>
    open ? <section role="dialog" aria-label={title}>{children}{footer}</section> : null);
  const host = document.createElement("div");
  const root = createRoot(host);
  try {
    await act(async () => root.render(<GenericWorkflowWorkspace team={team} teams={[]} onTeam={vi.fn()} onDiscussion={vi.fn()} onHistory={vi.fn()}/>));
    await act(async () => mocks.shell.mock.calls.at(-1)![0].onTemplate(preview.id));
    const dialog = host.querySelector('[role="dialog"][aria-label="创建你的流程"]')!;
    expect(dialog).not.toBeNull();
    expect(dialog.querySelector<HTMLInputElement>('[aria-label="流程名称"]')?.value).toBe(preview.name);
    expect(dialog.querySelector<HTMLSelectElement>('[aria-label="流程起点"]')?.value).toBe(preview.id);
    await act(async () => [...dialog.querySelectorAll("button")].find(button => button.textContent === "创建流程")!.click());
    expect(addFlow).toHaveBeenCalledOnce();
    const created: Flow = addFlow.mock.calls[0][0];
    expect(created.name).toBe(preview.name);
    expect(created.description).toBe(preview.description);
    expect(created.fields.length).toBeGreaterThan(0);
    expect(created.steps.map(step => step.label)).toEqual(preview.stepLabels);
    expect(created.steps.filter(step => step.kind === "agent" || step.kind === "output").map(step => step.owner)).toEqual(["researcher", "reviewer", "writer"]);
    expect(host.querySelector('[role="dialog"][aria-label="创建你的流程"]')).toBeNull();
  } finally { act(() => root.unmount()); }
});
