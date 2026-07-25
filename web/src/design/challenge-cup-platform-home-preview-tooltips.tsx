import { useEffect, useState } from "react";
import { createPortal } from "react-dom";
import { createRoot } from "react-dom/client";

import { VContextualHint, VTooltip } from "../components/vui";
import { VuiProvider } from "../components/vui/VuiProvider";
import "./tokens.css";
import "./base.css";
import "./tailwind.css";
import "./vui-provider-theme.css";
import "./vui-native-controls.css";

type HintTarget = HTMLElement & {
  dataset: DOMStringMap & {
    vuiHint?: string;
    vuiHintLabel?: string;
    vuiHintTitle?: string;
  };
};

function readTargets(): HintTarget[] {
  return Array.from(document.querySelectorAll<HintTarget>("[data-vui-hint]"));
}

function HintContent({ value }: { value: string }) {
  const lines = value.split("｜").map((line) => line.trim()).filter(Boolean);
  if (lines.length === 1) {
    return <span>{lines[0]}</span>;
  }
  return (
    <span className="grid gap-1">
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </span>
  );
}

function PreviewHints() {
  const [targets, setTargets] = useState<HintTarget[]>(readTargets);

  useEffect(() => {
    const observer = new MutationObserver(() => setTargets(readTargets()));
    observer.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-vui-hint", "data-vui-hint-label"],
      childList: true,
      subtree: true,
    });
    return () => observer.disconnect();
  }, []);

  return (
    <VuiProvider>
      {targets.map((target, index) => {
        const content = <HintContent value={target.dataset.vuiHint || ""} />;
        const hint = target.dataset.vuiHintTitle ? (
          <VTooltip content={content} width="wide">
            <strong tabIndex={target.closest("button") ? undefined : 0}>{target.dataset.vuiHintTitle}</strong>
          </VTooltip>
        ) : (
          <VContextualHint
            label={target.dataset.vuiHintLabel || "查看详细要求"}
            content={content}
            width="wide"
          />
        );
        return createPortal(
          hint,
          target,
          target.id || `${target.dataset.vuiHintLabel || "hint"}-${index}`,
        );
      })}
    </VuiProvider>
  );
}

const rootNode = document.createElement("div");
rootNode.hidden = true;
rootNode.setAttribute("aria-hidden", "true");
document.body.appendChild(rootNode);
createRoot(rootNode).render(<PreviewHints />);
