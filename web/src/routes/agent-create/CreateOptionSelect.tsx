import { ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";

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
  const optionRefs = useRef<Array<HTMLButtonElement | null>>([]);
  const [open, setOpen] = useState(false);
  const selected = options.find((option) => option.value === value);
  const triggerLabel = selected?.label || placeholder;
  const selectedIndex = options.findIndex((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    optionRefs.current[selectedIndex >= 0 ? selectedIndex : 0]?.focus();
  }, [open, selectedIndex]);

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

  const focusNextEnabledOption = (fromIndex: number, direction: 1 | -1) => {
    const length = options.length;
    if (length === 0) return;
    let target = -1;
    if (direction === 1) {
      for (let i = 1; i <= length; i += 1) {
        const index = (fromIndex + i) % length;
        if (!options[index].disabled) {
          target = index;
          break;
        }
      }
    } else {
      for (let i = 1; i <= length; i += 1) {
        const index = (fromIndex - i + length * 2) % length;
        if (!options[index].disabled) {
          target = index;
          break;
        }
      }
    }
    if (target >= 0) {
      optionRefs.current[target]?.focus();
    }
  };

  const handleTriggerKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>) => {
    if (!open) {
      return;
    }
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      focusNextEnabledOption(selectedIndex >= 0 ? selectedIndex : -1, event.key === "ArrowDown" ? 1 : -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      optionRefs.current[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      optionRefs.current[options.length - 1]?.focus();
    }
  };

  const handleOptionKeyDown = (event: ReactKeyboardEvent<HTMLButtonElement>, index: number) => {
    if (event.key === "ArrowDown") {
      event.preventDefault();
      focusNextEnabledOption(index, 1);
    } else if (event.key === "ArrowUp") {
      event.preventDefault();
      focusNextEnabledOption(index, -1);
    } else if (event.key === "Home") {
      event.preventDefault();
      optionRefs.current[0]?.focus();
    } else if (event.key === "End") {
      event.preventDefault();
      optionRefs.current[options.length - 1]?.focus();
    } else if (event.key === "Tab") {
      setOpen(false);
    }
  };

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
        onKeyDown={handleTriggerKeyDown}
      >
        <span className={styles.triggerText}>{triggerLabel}</span>
        <ChevronDown size={15} aria-hidden="true" />
      </VNativeButton>
      {open ? (
        <ul id={listId} className={styles.list} role="listbox" aria-label={label}>
          {options.map((option, index) => {
            const isSelected = option.value === value;
            return (
              <li key={option.value} role="presentation">
                <VNativeButton
                  ref={(node) => {
                    optionRefs.current[index] = node;
                  }}
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
                  onKeyDown={(event) => handleOptionKeyDown(event, index)}
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
