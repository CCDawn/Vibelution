import { forwardRef, useState, type ComponentPropsWithoutRef, type CSSProperties } from "react";

import styles from "./ShadcnRange.styles";

type Props = ComponentPropsWithoutRef<"input"> & {
  tickCount?: number;
  "data-vui"?: string;
  "data-density"?: string;
};

/** Native range semantics with the shared capsule presentation. */
export const ShadcnRange = forwardRef<HTMLInputElement, Props>(function ShadcnRange({
  tickCount,
  min = 0,
  max = 100,
  step = 1,
  value,
  defaultValue,
  onChange,
  disabled,
  className,
  style,
  ...props
}, ref) {
  const minimum = Number(min);
  const maximum = Number(max);
  const initial = Number(defaultValue ?? (minimum + maximum) / 2);
  const [uncontrolledValue, setUncontrolledValue] = useState(initial);
  const current = Number(value ?? uncontrolledValue);
  const progress = maximum > minimum && Number.isFinite(current)
    ? Math.max(0, Math.min(1, (current - minimum) / (maximum - minimum)))
    : 0;
  const wantedTicks = tickCount ?? (Math.floor((maximum - minimum) / (Number(step) || 1)) + 1);
  const count = Number.isFinite(wantedTicks) ? Math.max(1, Math.min(64, Math.floor(wantedTicks))) : 2;

  return (
    <div
      className={[styles.root, className].filter(Boolean).join(" ")}
      data-disabled={disabled ? "true" : "false"}
      style={{ "--vui-range-progress": `${progress * 100}%` } as CSSProperties}
    >
      <div className={styles.track} style={styles.trackPaint} aria-hidden="true" />
      <div className={styles.dots} aria-hidden="true">
        {Array.from({ length: count }, (_, index) => (
          <span key={index} className={styles.dot} data-filled={count > 1 && index / (count - 1) < progress ? "true" : "false"} />
        ))}
      </div>
      <input
        {...props}
        ref={ref}
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        defaultValue={defaultValue}
        disabled={disabled}
        className={styles.input}
        style={style}
        onChange={(event) => {
          if (value === undefined) setUncontrolledValue(Number(event.target.value));
          onChange?.(event);
        }}
      />
    </div>
  );
});
