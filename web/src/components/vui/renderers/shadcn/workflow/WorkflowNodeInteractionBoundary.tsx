import type { KeyboardEvent, MouseEvent, ReactNode } from "react";

export function WorkflowNodeInteractionBoundary(props: {
  onActivate?: () => void;
  children: ReactNode;
}) {
  const activateFromClick = (event: MouseEvent<HTMLDivElement>) => {
    if (!props.onActivate) return;
    event.stopPropagation();
    props.onActivate();
  };
  const activateFromKeyboard = (event: KeyboardEvent<HTMLDivElement>) => {
    if (!props.onActivate || (event.key !== "Enter" && event.key !== " ")) return;
    event.preventDefault();
    event.stopPropagation();
    props.onActivate();
  };

  return (
    <div
      className="h-full w-full overflow-visible"
      onClickCapture={activateFromClick}
      onKeyDown={activateFromKeyboard}
    >
      {props.children}
    </div>
  );
}
