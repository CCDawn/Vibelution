import { useLayoutEffect, useState } from "react";

/** Keep resting list edges on whole rows; the inset belongs outside the scroller. */
export function useWholeRowViewport() {
  const [host, ref] = useState<HTMLDivElement | null>(null);
  const [height, setHeight] = useState<number | undefined>();
  useLayoutEffect(() => {
    if (!host || typeof ResizeObserver === "undefined") return;
    const update = () => {
      const style = getComputedStyle(host);
      const row = Number.parseFloat(style.getPropertyValue("--config-list-row-height"));
      if (!Number.isFinite(row) || row <= 0) return;
      const inset = Number.parseFloat(style.paddingTop) + Number.parseFloat(style.paddingBottom);
      setHeight(Math.max(0, Math.floor((host.clientHeight - inset) / row)) * row);
    };
    const observer = new ResizeObserver(update);
    observer.observe(host);
    update();
    return () => observer.disconnect();
  }, [host]);
  return { ref, height };
}
