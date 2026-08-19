/** @vitest-environment happy-dom */
import React, { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { NodeCommandCapability } from "../../../api/types/researchWorkflow";
import { EvidenceRemediationDialog } from "./EvidenceRemediationDialog";

function capability(candidateIds: string[] = ["cand-b", "cand-a"]): NodeCommandCapability {
  return {
    command: "create_evidence_remediation_run",
    payload: { evidenceGapCandidateIds: candidateIds },
  } as unknown as NodeCommandCapability;
}

function setControlValue(element: Element, value: string) {
  const prototype = element instanceof HTMLTextAreaElement
    ? HTMLTextAreaElement.prototype
    : HTMLInputElement.prototype;
  Object.getOwnPropertyDescriptor(prototype, "value")?.set?.call(element, value);
  element.dispatchEvent(new Event("input", { bubbles: true }));
}

function buttonByText(text: string): HTMLButtonElement | undefined {
  return Array.from(document.body.querySelectorAll("button"))
    .find((button) => button.textContent?.includes(text));
}

async function mountDialog(props?: Partial<React.ComponentProps<typeof EvidenceRemediationDialog>>) {
  (globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
  const container = document.createElement("div");
  document.body.appendChild(container);
  const root = createRoot(container);
  const onSubmit = props?.onSubmit ?? vi.fn(async () => undefined);
  const onOpenChange = props?.onOpenChange ?? vi.fn();
  const render = (open: boolean) => (
    <EvidenceRemediationDialog
      open={open}
      capability={props?.capability === undefined ? capability() : props.capability}
      busy={false}
      onOpenChange={onOpenChange}
      onSubmit={onSubmit}
    />
  );
  await act(async () => {
    root.render(render(props?.open ?? true));
  });
  return {
    root,
    onSubmit,
    onOpenChange,
    async reopen() {
      await act(async () => {
        root.render(render(false));
      });
      await act(async () => {
        root.render(render(true));
      });
    },
  };
}

describe("EvidenceRemediationDialog", () => {
  let root: Root | null = null;

  afterEach(async () => {
    if (root) {
      await act(async () => root?.unmount());
      root = null;
    }
    document.body.innerHTML = "";
  });

  it("blocks submit until the operator reason is filled", async () => {
    const view = await mountDialog();
    root = view.root;

    expect(document.body.textContent).toContain("请填写本次补救原因");
    expect(buttonByText("创建子运行")!.disabled).toBe(true);
    expect(view.onSubmit).not.toHaveBeenCalled();
  });

  it("blocks submit when the capability carries no backend candidate ids", async () => {
    const view = await mountDialog({ capability: capability([]) });
    root = view.root;

    expect(document.body.textContent).toContain("缺少后端固化的证据缺口候选");
    expect(buttonByText("创建子运行")!.disabled).toBe(true);
  });

  it("requires at least one positive budget increment for add_budget", async () => {
    const view = await mountDialog();
    root = view.root;

    await act(async () => {
      setControlValue(document.body.querySelector("textarea")!, "补充关键证据缺口");
    });
    expect(document.body.textContent).toContain("追加预算至少有一项大于 0");
    expect(buttonByText("创建子运行")!.disabled).toBe(true);
  });

  it("submits the remediation payload and closes on success", async () => {
    const view = await mountDialog();
    root = view.root;

    await act(async () => {
      setControlValue(document.body.querySelector("textarea")!, "  补充关键证据缺口  ");
    });
    const budgetInputs = Array.from(document.body.querySelectorAll('input[type="number"]'));
    await act(async () => {
      setControlValue(budgetInputs[0], "5000");
    });
    await act(async () => {
      setControlValue(budgetInputs[2], "120");
    });

    const submit = buttonByText("创建子运行")!;
    expect(submit.disabled).toBe(false);
    await act(async () => {
      submit.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(view.onSubmit).toHaveBeenCalledTimes(1);
    const payload = (view.onSubmit as ReturnType<typeof vi.fn>).mock.calls[0][0] as Record<string, unknown>;
    expect(payload.resolutionKind).toBe("add_budget");
    expect(payload.operatorReason).toBe("补充关键证据缺口");
    expect(payload.evidenceGapCandidateIds).toEqual(["cand-a", "cand-b"]);
    expect(payload.additionalBudget).toEqual({
      tokens: 5000,
      toolCalls: 0,
      wallClockSeconds: 120,
      computeUnits: 0,
    });
    expect(view.onOpenChange).toHaveBeenCalledWith(false);
  });

  it("keeps the dialog open and shows the inline error when submit fails", async () => {
    const view = await mountDialog({
      onSubmit: vi.fn(async () => {
        throw new Error("预算超过安全上限");
      }),
    });
    root = view.root;

    await act(async () => {
      setControlValue(document.body.querySelector("textarea")!, "补充证据");
    });
    await act(async () => {
      setControlValue(document.body.querySelectorAll('input[type="number"]')[0], "100");
    });
    await act(async () => {
      buttonByText("创建子运行")!.dispatchEvent(new MouseEvent("click", { bubbles: true }));
    });

    expect(document.body.querySelector('[role="status"]')?.textContent).toContain("预算超过安全上限");
    expect(view.onOpenChange).not.toHaveBeenCalledWith(false);
  });

  it("resets the form draft when the dialog is reopened", async () => {
    const view = await mountDialog();
    root = view.root;

    await act(async () => {
      setControlValue(document.body.querySelector("textarea")!, "上一次填写的原因");
    });
    await view.reopen();

    const textarea = document.body.querySelector("textarea")!;
    expect(textarea.value).toBe("");
    expect(document.body.textContent).toContain("请填写本次补救原因");
  });
});
