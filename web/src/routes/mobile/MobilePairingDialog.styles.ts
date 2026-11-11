const scope = "vui-routes-mobile-mobilepairingdialog";
function cv(key: string, ...classNames: string[]) {
  return [scope, key, ...classNames].join(" ");
}
const styles = {
  content: cv("content", "flex flex-col gap-3 text-sm"),
  hint: cv("hint", "m-0 text-vui-fg-secondary"),
  error: cv("error", "m-0 text-vui-danger"),
  codeCard: cv(
    "code-card",
    "flex flex-col gap-2 rounded-vui-md border border-vui-border bg-vui-surface-sunken p-3",
  ),
  codeLabel: cv("code-label", "text-xs uppercase tracking-wide text-vui-fg-tertiary"),
  codeValue: cv(
    "code-value",
    "font-mono text-2xl font-semibold tracking-[0.2em] text-vui-fg-primary",
  ),
  codeMeta: cv("code-meta", "text-xs text-vui-fg-tertiary"),
  payload: cv("payload", "m-0 break-all text-xs text-vui-fg-tertiary"),
  actions: cv("actions", "flex justify-end gap-2 pt-1"),
};
export default styles;
