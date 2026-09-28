/**
 * 数字步进器 —— ZCode FontSizeInput 模式（number input + step 1 + min/max 硬钳制）。
 * 同时用于顶部基准切换器（14–18）与设置行样张里的数字控件（更宽域）——
 * 正好检验控件高度与字号放大的协调性。组合全部为现有 VUI 控件：VButton + VInput。
 */
import { useEffect, useState } from "react";
import { Minus, Plus } from "lucide-react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { VInput } from "../../../src/components/vui/forms/VInput";

export type NumberStepperProps = {
  value: number;
  min: number;
  max: number;
  step?: number;
  onChange: (next: number) => void;
  ariaLabel: string;
  testId?: string;
};

function bound(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

export function NumberStepper({
  value,
  min,
  max,
  step = 1,
  onChange,
  ariaLabel,
  testId,
}: NumberStepperProps) {
  // 输入中的草稿文本：允许临时越界/空串，失焦或回车时钳制归位。
  const [draft, setDraft] = useState<string>(String(value));
  const [focused, setFocused] = useState(false);

  useEffect(() => {
    if (!focused) {
      setDraft(String(value));
    }
  }, [value, focused]);

  const commit = () => {
    setFocused(false);
    const parsed = Number(draft);
    const next = bound(Number.isFinite(parsed) ? Math.round(parsed) : value, min, max);
    setDraft(String(next));
    if (next !== value) {
      onChange(next);
    }
  };

  const stepBy = (direction: 1 | -1) => {
    const next = bound(value + direction * step, min, max);
    setDraft(String(next));
    if (next !== value) {
      onChange(next);
    }
  };

  return (
    <span
      className="inline-flex items-center gap-1"
      data-testid={testId}
      data-vui="number-stepper"
    >
      <VButton
        variant="secondary"
        isIconOnly
        aria-label={`${ariaLabel} decrease`}
        data-testid={testId ? `${testId}-dec` : undefined}
        onClick={() => stepBy(-1)}
      >
        <Minus />
      </VButton>
      <VInput
        type="number"
        aria-label={ariaLabel}
        data-testid={testId ? `${testId}-input` : undefined}
        value={draft}
        min={min}
        max={max}
        step={step}
        className="w-16 text-center tabular-nums"
        onFocus={() => setFocused(true)}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            commit();
          }
        }}
      />
      <VButton
        variant="secondary"
        isIconOnly
        aria-label={`${ariaLabel} increase`}
        data-testid={testId ? `${testId}-inc` : undefined}
        onClick={() => stepBy(1)}
      >
        <Plus />
      </VButton>
    </span>
  );
}
