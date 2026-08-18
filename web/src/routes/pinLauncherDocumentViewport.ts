export type LauncherViewportPinStyle = {
  maxWidth: string;
  minWidth: string;
  overflowX: string;
  width: string;
};

export type LauncherVisibleCssWidthInput = {
  clientWidth?: number;
  designedWidthPx?: number;
  devicePixelRatio?: number;
  innerWidth?: number;
  visualViewportWidth?: number;
};

/** Matches `createLauncherWindow` default width in desktop/electron. */
export const LAUNCHER_CONTROL_WINDOW_WIDTH_PX = 1180;

/**
 * Electron sizes the HWND in physical pixels matching `width: 1180`, while the
 * renderer `--device-scale-factor` is 1.25. `clientWidth` / `innerWidth` then
 * report ~1180 CSS px for a surface that only paints ~1180/dpr CSS px. Dividing
 * that DIP-sized reading by DPR yields the visible CSS width; already-small
 * readings (true CSS px) are left alone.
 */
export function resolveLauncherVisibleCssWidth(input: LauncherVisibleCssWidthInput = {}): number {
  const designed = input.designedWidthPx ?? LAUNCHER_CONTROL_WINDOW_WIDTH_PX;
  const dpr = Number(input.devicePixelRatio) || 1;
  const raw =
    Number(input.visualViewportWidth) ||
    Number(input.clientWidth) ||
    Number(input.innerWidth) ||
    designed;
  if (dpr > 1.05 && raw >= designed - 40) {
    return Math.max(320, Math.round(raw / dpr));
  }
  return Math.max(320, Math.round(raw));
}

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
  widthPx: number = resolveLauncherVisibleCssWidth({
    clientWidth: Number(doc.documentElement?.clientWidth) || 0,
    innerWidth: Number(doc.defaultView?.innerWidth) || 0,
    visualViewportWidth: Number(doc.defaultView?.visualViewport?.width) || 0,
    devicePixelRatio: Number(doc.defaultView?.devicePixelRatio) || 1,
  }),
): () => void {
  const width = `${Math.max(320, Math.round(widthPx))}px`;
  if (doc.documentElement && "style" in doc.documentElement) {
    doc.documentElement.style.setProperty("--vui-window-width", width);
  }
  const nodes = [doc.documentElement, doc.body, doc.getElementById("root")].filter(
    (node): node is HTMLElement => Boolean(node && typeof node === "object" && "style" in node),
  );
  const restores = nodes.map((node) => pinElement(node, `min(${width}, 100svw)`));
  return () => {
    for (const restore of restores) {
      restore();
    }
  };
}
