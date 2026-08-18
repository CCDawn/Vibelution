export type LauncherViewportPinStyle = {
  maxWidth: string;
  minWidth: string;
  overflowX: string;
  width: string;
};

const PINNED_STYLE: LauncherViewportPinStyle = {
  overflowX: "clip",
  maxWidth: "100%",
  width: "100%",
  minWidth: "0",
};

function pinElement(element: HTMLElement): () => void {
  const previous: LauncherViewportPinStyle = {
    overflowX: element.style.overflowX,
    maxWidth: element.style.maxWidth,
    width: element.style.width,
    minWidth: element.style.minWidth,
  };
  element.style.overflowX = PINNED_STYLE.overflowX;
  element.style.maxWidth = PINNED_STYLE.maxWidth;
  element.style.width = PINNED_STYLE.width;
  element.style.minWidth = PINNED_STYLE.minWidth;
  return () => {
    element.style.overflowX = previous.overflowX;
    element.style.maxWidth = previous.maxWidth;
    element.style.width = previous.width;
    element.style.minWidth = previous.minWidth;
  };
}

export function pinLauncherDocumentViewport(doc: Document): () => void {
  const nodes = [doc.documentElement, doc.body, doc.getElementById("root")].filter(
    (node): node is HTMLElement => Boolean(node && typeof node === "object" && "style" in node),
  );
  const restores = nodes.map((node) => pinElement(node));
  return () => {
    for (const restore of restores) {
      restore();
    }
  };
}
