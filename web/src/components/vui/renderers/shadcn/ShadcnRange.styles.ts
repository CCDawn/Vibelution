const styles = {
  root: "relative h-10 min-w-0 data-[disabled=true]:opacity-55",
  track: "pointer-events-none absolute inset-x-0 inset-y-2 rounded-full border border-[color-mix(in_srgb,var(--fg-primary)_16%,transparent)]",
  trackPaint: { backgroundImage: "linear-gradient(to right, var(--fg-primary) 0 var(--vui-range-progress), color-mix(in srgb, var(--fg-primary) 9%, var(--vui-surface-panel)) var(--vui-range-progress) 100%)" },
  dots: "pointer-events-none absolute inset-y-0 left-3.5 right-3.5 flex items-center justify-between",
  dot: "size-1 rounded-full bg-[color-mix(in_srgb,var(--fg-primary)_36%,var(--vui-surface-panel))] data-[filled=true]:bg-[color-mix(in_srgb,var(--vui-surface-panel)_28%,var(--fg-primary))]",
  input: "absolute -top-0.5 left-0 z-[1] m-0 h-11 min-h-11 w-full min-w-0 cursor-pointer appearance-none rounded-full border-0 bg-transparent p-0 shadow-none focus-visible:outline focus-visible:outline-1 focus-visible:outline-offset-2 focus-visible:outline-[var(--fg-tertiary)] disabled:cursor-default [&::-webkit-slider-runnable-track]:h-6 [&::-webkit-slider-runnable-track]:border-0 [&::-webkit-slider-runnable-track]:bg-transparent [&::-webkit-slider-thumb]:-mt-0.5 [&::-webkit-slider-thumb]:size-7 [&::-webkit-slider-thumb]:appearance-none [&::-webkit-slider-thumb]:rounded-full [&::-webkit-slider-thumb]:border [&::-webkit-slider-thumb]:border-[color-mix(in_srgb,var(--fg-primary)_22%,transparent)] [&::-webkit-slider-thumb]:bg-[var(--vui-surface-panel)] [&::-webkit-slider-thumb]:shadow-none [&::-moz-range-track]:h-6 [&::-moz-range-track]:border-0 [&::-moz-range-track]:bg-transparent [&::-moz-range-progress]:bg-transparent [&::-moz-range-thumb]:size-7 [&::-moz-range-thumb]:rounded-full [&::-moz-range-thumb]:border [&::-moz-range-thumb]:border-[color-mix(in_srgb,var(--fg-primary)_22%,transparent)] [&::-moz-range-thumb]:bg-[var(--vui-surface-panel)] [&::-moz-range-thumb]:shadow-none",
};

export default styles;
