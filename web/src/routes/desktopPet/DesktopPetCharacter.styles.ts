const styles = {
  root: "desktop-pet-character",
  halo: "desktop-pet-character__halo",
  canvas: "desktop-pet-character__canvas",
  frame: "desktop-pet-character__frame",
  message: "absolute inset-x-3 top-1/2 z-10 rounded-lg bg-[var(--vui-pet-message-bg)] p-3 text-center text-xs text-[var(--vui-pet-fg-bright)]",
  credit: "absolute bottom-0 left-1/2 z-10 -translate-x-1/2 whitespace-nowrap rounded bg-[var(--vui-pet-credit-bg)] px-1 [font-size:var(--vui-pet-credit-size)] text-[var(--vui-pet-credit-fg)]",
} as const;

export default styles;
