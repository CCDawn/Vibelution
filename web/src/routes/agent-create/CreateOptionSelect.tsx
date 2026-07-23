import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState } from "react";

import { VNativeButton } from "../../components/vui";
import styles from "./CreateOptionSelect.styles";

export type CreateOptionSelectItem = {
  value: string;
  label: string;
  disabled?: boolean;
  description?: string;
};

type CreateOptionSelectProps = {
  label: string;
  value: string;
  options: CreateOptionSelectItem[];
  disabled?: boolean;
  placeholder?: string;
  onChange: (value: string) => void;
};

/**
 * Modal-safe option picker. Native select dropdowns often fail to open inside
 * overflow/backdrop-blur dialogs (Windows desktop shell), so this uses an
 * in-panel listbox instead.
 */
export function CreateOptionSelect({
  label,
  value,
  options,
  disabled = false,
  placeholder = "-",
  onChange,
}: CreateOptionSelectProps) {
  const listId = useId();
  const rootRef = useRef<HTMLDivElement>(null);
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);
  const triggerLabel = selected?.label || placeholder;

  useEffect(() => {
    if (!open) return;
    const onPointerDown = (event: MouseEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onPointerDown);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("mousedown", onPointerDown);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [open]);

  return (
    <div ref={rootRef} className={styles.root}>
      <VNativeButton
        type="button"
        className={[styles.trigger, selected && selected.disabled ? styles.triggerMuted : ""].filter(Boolean).join(" ")}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={listId}
        aria-label={label}
        disabled={disabled || options.length === 0}
        onClick={() => setOpen((current) => !current)}
      >
        <span className={styles.triggerText}>{triggerLabel}</span>
        <ChevronDown size={15} aria-hidden="true" />
      </VNativeButton>
      {open ? (
        <ul id={listId} className={styles.list} role="listbox" aria-label={label}>
          {options.map((option) => {
            const isSelected = option.value === value;
            return (
              <li key={option.value} role="presentation">
                <VNativeButton
                  type="button"
                  role="option"
                  aria-selected={isSelected}
                  disabled={option.disabled}
                  title={option.description || option.label}
                  className={[
                    styles.option,
                    isSelected ? styles.optionSelected : "",
                    option.disabled ? styles.optionDisabled : "",
                  ].filter(Boolean).join(" ")}
                  onClick={() => {
                    if (option.disabled) return;
                    onChange(option.value);
                    setOpen(false);
                  }}
                >
                  <span>{option.label}</span>
                  {option.description ? <small>{option.description}</small> : null}
                </VNativeButton>
              </li>
            );
          })}
        </ul>
      ) : null}
    </div>
  );
}
