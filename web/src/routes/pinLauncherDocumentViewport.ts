export type LauncherViewportPinStyle = {
  maxWidth: string;
  minWidth: string;
  overflowX: string;
  width: string;
};

/** Matches `createLauncherWindow` default width in desktop/electron. */
export const LAUNCHER_CONTROL_WINDOW_WIDTH_PX = 1180;

function pinElement(element: HTMLElement, width: string): () => void {
  const previous: LauncherViewportPinStyle = {
    overflowX: element.style.overflowX,
    maxWidth: element.style.maxWidth,
    width: element.style.width,
    minWidth: element.style.minWidth,
  };
  element.style.overflowX = "clip";
  element.style.maxWidth = width;
  element.style.width = width;
  element.style.minWidth = "0";
  return () => {
    element.style.overflowX = previous.overflowX;
    element.style.maxWidth = previous.maxWidth;
    element.style.width = previous.width;
    element.style.minWidth = previous.minWidth;
  };
}

export function pinLauncherDocumentViewport(
  doc: Document,
  widthPx: number = LAUNCHER_CONTROL_WINDOW_WIDTH_PX,
): () => void {
  const width = `${Math.max(320, Math.round(widthPx))}px`;
  const nodes = [doc.documentElement, doc.body, doc.getElementById("root")].filter(
    (node): node is HTMLElement => Boolean(node && typeof node === "object" && "style" in node),
  );
  const restores = nodes.map((node) => pinElement(node, width));
  return () => {
    for (const restore of restores) {
      restore();
    }
  };
}
