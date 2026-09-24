/*
 * Preview wiring: global toggles + live computed-style probes.
 * The takeover mechanism itself lives in takeover.css (pure CSS custom
 * property overrides) — this file only flips attributes and reads back
 * getComputedStyle so the page shows the resolved px values.
 */

import "./tokens-preview-copy.css";
import "./takeover.css";
import "./preview.css";

function refreshProbes(): void {
  for (const el of Array.from(document.querySelectorAll<HTMLElement>("[data-probe]"))) {
    const computed = window.getComputedStyle(el);
    const out = el.closest(".probe-line, .demo-row")?.querySelector<HTMLElement>(".probe-out");
    if (!out) {
      continue;
    }
    const sizePx = Number.parseFloat(computed.fontSize);
    const lhValue = computed.lineHeight;
    const lhPx = lhValue === "normal" ? "normal" : `${Number.parseFloat(lhValue).toFixed(1)}px`;
    const lhRatio =
      lhValue === "normal" ? "normal" : (Number.parseFloat(lhValue) / sizePx).toFixed(3);
    out.textContent = `${computed.fontSize} / ${lhPx} (${lhRatio})`;
  }
}

function bindToggle(attr: string, id: string): void {
  const input = document.getElementById(id) as HTMLInputElement | null;
  if (!input) {
    return;
  }
  const apply = (): void => {
    if (input.checked) {
      document.documentElement.setAttribute(attr, "on");
    } else {
      document.documentElement.removeAttribute(attr);
    }
    window.requestAnimationFrame(refreshProbes);
  };
  input.addEventListener("change", apply);
  apply();
}

function bindThemeToggle(): void {
  const select = document.getElementById("theme-select") as HTMLSelectElement | null;
  if (!select) {
    return;
  }
  const apply = (): void => {
    if (select.value === "light") {
      document.documentElement.setAttribute("data-theme", "light");
    } else {
      document.documentElement.removeAttribute("data-theme");
    }
  };
  select.addEventListener("change", apply);
  apply();
}

function main(): void {
  bindToggle("data-takeover", "toggle-takeover");
  bindToggle("data-lh-pairing", "toggle-lh");
  bindThemeToggle();
  window.addEventListener("load", refreshProbes);
  refreshProbes();
}

main();
