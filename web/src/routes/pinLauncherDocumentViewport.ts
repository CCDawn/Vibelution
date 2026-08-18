export type LauncherViewportPinStyle = {
  maxWidth: string;
  minWidth: string;
  overflowX: string;
  width: string;
};

const DOCUMENT_WIDTH = "100%";
const WINDOW_WIDTH_VAR = "100svw";

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

/**
 * Fill the Electron client area instead of shrinking `html`/`body`/`#root` to a
 * one-shot pixel cap. Dividing `clientWidth` by `devicePixelRatio` left a
 * leftover strip of window chrome because BrowserWindow `width` is already DIP.
 * `overflow-x: clip` still stops dense tables from expanding the layout viewport.
 */
export function pinLauncherDocumentViewport(doc: Document): () => void {
  if (doc.documentElement && "style" in doc.documentElement) {
    doc.documentElement.style.setProperty("--vui-window-width", WINDOW_WIDTH_VAR);
  }
  const nodes = [doc.documentElement, doc.body, doc.getElementById("root")].filter(
    (node): node is HTMLElement => Boolean(node && typeof node === "object" && "style" in node),
  );
  const restores = nodes.map((node) => pinElement(node, DOCUMENT_WIDTH));
  return () => {
    for (const restore of restores) {
      restore();
    }
  };
}
