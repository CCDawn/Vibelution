/** @vitest-environment happy-dom */
import React, { act, type ComponentProps, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Run } from "./workflowModel";
import { WorkbenchShell } from "./WorkbenchShell";
import { createWorkflow, workflowTemplatePreviews } from "./workflowTemplates";

vi.mock("./FlowEditor", () => ({ FlowEditor: () => <div aria-label="流程编辑器"/> }));
vi.mock("../../../components/vui", () => {
  type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
    isDisabled?: boolean; isPending?: boolean; icon?: ReactNode; label?: string;
  };
  const Button = ({ children, onClick, isDisabled, isPending, label, ...props }: ButtonProps) =>
    <button aria-label={props["aria-label"] ?? label} aria-pressed={props["aria-pressed"]}
      aria-busy={isPending || undefined} disabled={isDisabled} onClick={onClick}>{children ?? label}</button>;
  return {
    VSkeleton: ({ className }: { className?: string }) => <span data-vui="skeleton" className={className}/>,
    VButton: Button, VIconButton: Button, VNativeButton: Button,
    VCanvasWorkbenchPage: ({ rail, canvas, inspector }: { rail: ReactNode; canvas: ReactNode; inspector: ReactNode }) =>
      <div>{rail}{canvas}{inspector}</div>,
    VSelect: ({ options, selectedKey, onSelectionChange, "aria-label": label }: {
      options: { id: string; label: string }[]; selectedKey: string;
      onSelectionChange: (value: string) => void; "aria-label": string;
    }) => <select aria-label={label} value={selectedKey} onChange={event => onSelectionChange(event.target.value)}>
      {options.map(item => <option key={item.id} value={item.id}>{item.label}</option>)}
    </select>,
    VTabs: ({ items, value, onValueChange, "aria-label": label }: {
      items: { id: string; label: string }[]; value: string;
      onValueChange: (value: string) => void; "aria-label": string;
    }) => <div role="tablist" aria-label={label}>{items.map(item =>
      <button key={item.id} role="tab" aria-selected={value === item.id} onClick={() => onValueChange(item.id)}>{item.label}</button>)}</div>,
  };
});
(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;

let host: HTMLDivElement;
let root: Root;
beforeEach(() => { host = document.createElement("div"); document.body.append(host); root = createRoot(host); });
afterEach(() => { act(() => root.unmount()); host.remove(); });

function shellProps(overrides: Partial<ComponentProps<typeof WorkbenchShell>> = {}): ComponentProps<typeof WorkbenchShell> {
  return {
    flows: [], runs: [], mode: "design", teamId: "real-team", teams: [{ id: "real-team", label: "实际团队" }],
    members: [], saving: false, pending: false, loading: false, error: "", selectedId: "", dirty: false,
    inspector: null, notice: "", inspectorOpen: false,
    onTeam: vi.fn(), onDiscussion: vi.fn(), onHistory: vi.fn(), onReload: vi.fn(), onInspectorOpen: vi.fn(),
    onMode: vi.fn(), onFlow: vi.fn(), onStep: vi.fn(), onRun: vi.fn(), onSave: vi.fn(), onStart: vi.fn(),
    onStop: vi.fn(), onCreate: vi.fn(), onTemplate: vi.fn(), onAddStep: vi.fn(), onMembers: vi.fn(),
    onArtifact: vi.fn(), onDismiss: vi.fn(), ...overrides,
  };
}
const render = async (props: ComponentProps<typeof WorkbenchShell>) => { await act(async () => root.render(<WorkbenchShell {...props}/>)); };
const button = (text: string) => [...host.querySelectorAll("button")].find(item => item.textContent === text);
const flow = createWorkflow("实际流程", "blank", []);
const run = (overrides: Partial<Run> = {}): Run => ({
  id: "run-real", teamId: "real-team", flow, values: {}, status: "running", current: 0, revision: 1, messages: [], ...overrides,
});

it("shows real template previews and creation actions without draft controls before a flow exists", async () => {
  const props = shellProps();
  await render(props);
  expect(host.textContent).toContain("从一个流程开始协作");
  expect(host.textContent).not.toContain("已保存");
  expect(host.querySelector('[role="tablist"][aria-label="工作模式"]')).toBeNull();
  expect(button("保存")).toBeUndefined();
  expect(button("试运行")).toBeUndefined();
  expect(host.querySelectorAll("article")).toHaveLength(workflowTemplatePreviews.length);
  for (const preview of workflowTemplatePreviews) {
    const card = [...host.querySelectorAll("article")].find(item => item.querySelector("h4")?.textContent === preview.name)!;
    expect(card).toBeDefined();
    expect(card.textContent).toContain(preview.description);
    expect(card.textContent).toContain(`${preview.stepCount} 个步骤`);
    for (const label of preview.stepLabels) expect(card.textContent).toContain(label);
    await act(async () => card.querySelector("button")!.click());
    expect(props.onTemplate).toHaveBeenLastCalledWith(preview.id);
  }
  expect([...host.querySelectorAll("h4")].map(item => item.textContent)).toEqual(["资料调研与交叉验证", "文档审查"]);
  await act(async () => button("创建流程")!.click());
  expect(props.onCreate).toHaveBeenCalledOnce();
});

it("reserves the real starting-page geometry while loading without announcing an empty workspace or enabling creation", async () => {
  const props = shellProps({ loading: true, teamPending: true });
  await render(props);
  expect(host.querySelector('[data-team-workspace-start]')?.getAttribute("aria-hidden")).toBe("true");
  expect(host.querySelector('[data-team-workspace-loading]')?.getAttribute("aria-busy")).toBe("true");
  expect(host.querySelector('[role="status"]')?.textContent).toBe("正在读取流程…");
  expect(host.textContent).not.toContain("还没有流程");
  expect(host.textContent).not.toContain("位成员可用");
  expect(button("创建流程")?.disabled).toBe(true);
  expect(button("使用模板")?.disabled).toBe(true);
  expect(button("新建流程")?.disabled).toBe(true);
  await act(async () => button("创建流程")!.click());
  expect(props.onCreate).not.toHaveBeenCalled();
});

it("keeps the actual editor and inspector in place when loading with known flow data", async () => {
  await render(shellProps({ loading: true, flow, flows: [flow], inspector: <div aria-label="节点配置内容"/> }));
  expect(host.querySelector('[aria-label="流程编辑器"]')).not.toBeNull();
  expect(host.querySelector('[aria-label="节点配置内容"]')).not.toBeNull();
  expect(host.querySelector('[data-team-workspace-start]')).toBeNull();
  expect(button("保存")?.disabled).toBe(true);
  expect(button("试运行")?.disabled).toBe(true);
});

it("does not present the empty starting page after an error", async () => {
  const props = shellProps({ error: "读取失败，请稍后重试" });
  await render(props);
  expect(host.textContent).not.toContain("从一个流程开始协作");
  expect(button("使用模板")).toBeUndefined();
  expect(button("创建流程")).toBeUndefined();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain(props.error);
  await act(async () => button("重新读取")!.click());
  expect(props.onReload).toHaveBeenCalledOnce();
});

it("keeps design controls available for a selected saved flow", async () => {
  const props = shellProps({ flow, flows: [flow] });
  await render(props);
  expect(host.textContent).toContain("已保存");
  expect(host.querySelector('[role="tablist"][aria-label="工作模式"]')).not.toBeNull();
  await act(async () => button("保存")!.click());
  await act(async () => button("试运行")!.click());
  expect(props.onSave).toHaveBeenCalledOnce();
  expect(props.onStart).toHaveBeenCalledOnce();
});

it.each(["running", "waiting"] as const)("disables Stop while a %s command is pending without claiming a stop request", async status => {
  const props = shellProps({ flow, flows: [flow], run: run({ status }), mode: "run", pending: true });
  await render(props);
  expect(button("停止")?.disabled).toBe(true);
  expect(button("停止")?.getAttribute("aria-busy")).toBe("true");
  await act(async () => button("停止")!.click());
  expect(props.onStop).not.toHaveBeenCalled();
});

it.each(["running", "waiting"] as const)("shows a disabled stopping action after a %s run accepts a stop request", async status => {
  const props = shellProps({ flow, flows: [flow], run: run({ status, stopRequested: true }), mode: "run" });
  await render(props);
  expect(button("正在停止")?.disabled).toBe(true);
  expect(button("正在停止")?.getAttribute("aria-busy")).toBe("true");
  expect(button("停止")).toBeUndefined();
  await act(async () => button("正在停止")!.click());
  expect(props.onStop).not.toHaveBeenCalled();
});

it.each([
  { status: "running", attemptStatus: undefined, available: false },
  { status: "failed", attemptStatus: "running", available: false },
  { status: "stopped", attemptStatus: undefined, available: false },
  { status: "waiting", attemptStatus: undefined, available: true },
  { status: "completed", attemptStatus: undefined, available: true },
  { status: "running", attemptStatus: "completed", available: true },
  { status: "failed", attemptStatus: "completed", available: true },
] satisfies { status: Run["status"]; attemptStatus: string | undefined; available: boolean }[])(
  "gates artifacts for $status runs with a $attemptStatus attempt", async ({ status, attemptStatus, available }) => {
    const attempts = attemptStatus ? [{ nodeId: "work", number: 1, agentId: "real-member", sessionId: "native-session", turnId: "native-turn", key: "attempt-1", status: attemptStatus }] : undefined;
    const props = shellProps({ flow, flows: [flow], run: run({ status, attempts }), mode: "run" });
    await render(props);
    await act(async () => button("产物")!.click());
    if (available) {
      expect(button("查看产物")).toBeDefined();
      await act(async () => button("查看产物")!.click());
      expect(props.onArtifact).toHaveBeenCalledOnce();
    } else {
      expect(button("查看产物")).toBeUndefined();
      expect(host.textContent).toContain("完成相关步骤后，产物会显示在这里。");
    }
  },
);
