type VuiStyleMapOptions = {
  baseClassName?: string;
  extensions?: Record<string, string>;
  includeKeyClass?: boolean;
  overrides?: Record<string, string>;
};

const BASE = "min-w-0";
const SURFACE =
  "min-w-0 rounded-[var(--radius-panel)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-glass)] shadow-[var(--vui-shadow-hairline)]";
const PANEL = `${SURFACE} p-2`;
const ROW =
  "min-w-0 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)]";
const BUTTON =
  "inline-flex min-h-[var(--vui-control-height-sm)] w-fit max-w-full items-center justify-center gap-1.5 rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 py-1 text-[var(--vui-font-xs)] font-semibold leading-tight text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)] disabled:cursor-default disabled:opacity-55";
const ICON_BUTTON =
  "inline-grid h-[var(--vui-control-height-sm)] min-h-[var(--vui-control-height-sm)] w-[var(--vui-control-height-sm)] min-w-[var(--vui-control-height-sm)] place-items-center rounded-[var(--radius-control)] border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] p-0 text-[var(--fg-secondary)] hover:border-[var(--border-strong)] hover:bg-[var(--vui-control-muted-hover)] hover:text-[var(--fg-primary)]";
const PILL =
  "inline-flex min-h-6 w-fit max-w-full items-center justify-center gap-1.5 rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)] px-2 text-[var(--vui-font-xs)] font-semibold leading-none text-[var(--fg-secondary)]";
const FIELD =
  "grid min-w-0 gap-1 text-[var(--vui-font-xs)] text-[var(--fg-secondary)] [&_input]:min-h-[var(--vui-control-height-sm)] [&_select]:min-h-[var(--vui-control-height-sm)] [&_textarea]:min-h-20 [&_input]:w-full [&_select]:w-full [&_textarea]:w-full";
const TEXT =
  "min-w-0 text-[var(--vui-font-sm)] leading-[var(--vui-line-readable)] text-[var(--fg-secondary)]";
const TITLE = "min-w-0 text-[var(--vui-font-title)] font-semibold leading-tight text-[var(--fg-primary)]";
const MUTED = "min-w-0 text-[var(--vui-font-xs)] leading-tight text-[var(--fg-tertiary)]";

const toneClasses: Record<string, string> = {
  active:
    "border-[color-mix(in_srgb,var(--accent-cool)_34%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_10%,var(--vui-surface-row))] text-[var(--accent-cool)]",
  agent:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  blocked:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  caution:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  completed:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  context:
    "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  danger:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  error:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  failed:
    "border-[color-mix(in_srgb,var(--state-error)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-error)_9%,transparent)] text-[var(--state-error)]",
  idle:
    "border-[var(--vui-border-subtle)] bg-[var(--vui-surface-row)] text-[var(--fg-tertiary)]",
  info:
    "border-[color-mix(in_srgb,var(--accent-cool)_28%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] text-[var(--accent-cool)]",
  live:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  ok:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  partial:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
  ready:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  running:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  selected:
    "border-[color-mix(in_srgb,var(--accent-cool)_38%,transparent)] bg-[color-mix(in_srgb,var(--accent-cool)_11%,transparent)] text-[var(--accent-cool)]",
  success:
    "border-[color-mix(in_srgb,var(--state-success)_32%,transparent)] bg-[color-mix(in_srgb,var(--state-success)_9%,transparent)] text-[var(--state-success)]",
  tool:
    "border-[color-mix(in_srgb,var(--accent-warm)_24%,transparent)] bg-[color-mix(in_srgb,var(--accent-warm)_8%,transparent)] text-[var(--accent-warm)]",
  warning:
    "border-[color-mix(in_srgb,var(--state-warning)_36%,transparent)] bg-[color-mix(in_srgb,var(--state-warning)_10%,transparent)] text-[var(--state-warning)]",
};

function splitKey(key: string): string[] {
  return key
    .replace(/([a-z])([A-Z])/g, "$1 $2")
    .replaceAll("_", " ")
    .replaceAll("-", " ")
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
}

function includesAny(words: string[], values: string[]): boolean {
  return values.some((value) => words.includes(value));
}

function toneFor(words: string[]): string {
  for (const [tone, className] of Object.entries(toneClasses)) {
    if (words.includes(tone)) {
      return className;
    }
  }
  return "";
}

function classesForKey(key: string): string {
  const words = splitKey(key);
  const classes = [BASE];

  if (includesAny(words, ["route", "shell"])) {
    classes.push("grid h-full min-h-0 content-start overflow-hidden bg-[var(--surface-page)] text-[var(--fg-primary)]");
  }
  if (includesAny(words, ["workspace", "canvas", "layout"])) {
    classes.push("grid min-h-0 min-w-0 gap-2 p-2");
  }
  if (includesAny(words, ["panel", "card", "surface", "box", "notice", "summary", "detail", "editor", "preview"])) {
    classes.push(PANEL);
  }
  if (includesAny(words, ["header", "toolbar", "actions", "action", "controls", "control", "footer", "meta", "bar", "strip"])) {
    classes.push("flex min-w-0 flex-wrap items-center gap-1.5");
  }
  if (includesAny(words, ["grid", "cards", "columns", "stats", "metrics", "subgrid"])) {
    classes.push("grid min-w-0 gap-2");
  }
  if (includesAny(words, ["list", "queue", "timeline", "items", "tree", "rail"])) {
    classes.push("grid min-h-0 min-w-0 content-start gap-1.5 overflow-auto");
  }
  if (includesAny(words, ["row", "item", "turn", "entry", "line"])) {
    classes.push(`${ROW} p-2`);
  }
  if (includesAny(words, ["button", "trigger", "tab", "link"])) {
    classes.push(includesAny(words, ["icon", "round", "avatar"]) ? ICON_BUTTON : BUTTON);
  }
  if (includesAny(words, ["primary"])) {
    classes.push(toneClasses.active);
  }
  if (includesAny(words, ["danger", "delete", "remove", "error", "failed"])) {
    classes.push(toneClasses.danger);
  }
  if (includesAny(words, ["pill", "badge", "chip", "tag", "state", "status", "role", "count"])) {
    classes.push(PILL);
  }
  if (includesAny(words, ["dot"])) {
    classes.push("inline-block h-2 w-2 rounded-full bg-current");
  }
  if (includesAny(words, ["avatar"])) {
    classes.push("inline-grid h-8 w-8 shrink-0 place-items-center overflow-hidden rounded-full border border-[var(--vui-border-subtle)] bg-[var(--vui-control-muted)]");
  }
  if (includesAny(words, ["identity"])) {
    classes.push("grid min-w-0 gap-1");
  }
  if (includesAny(words, ["icon"])) {
    classes.push("shrink-0 text-[var(--fg-tertiary)]");
  }
  if (includesAny(words, ["field", "input", "select", "textarea", "form"])) {
    classes.push(FIELD);
  }
  if (includesAny(words, ["title", "headline", "name"])) {
    classes.push(TITLE);
  }
  if (includesAny(words, ["subtitle", "copy", "text", "body", "description", "lead", "reason", "message", "content"])) {
    classes.push(TEXT);
  }
  if (includesAny(words, ["eyebrow", "hint", "empty", "muted", "quiet", "timestamp", "time", "label", "caption"])) {
    classes.push(MUTED);
  }
  if (includesAny(words, ["code", "path", "json", "args", "schema", "log"])) {
    classes.push("font-mono text-[var(--vui-font-xs)]");
  }
  if (includesAny(words, ["collapsed", "hidden"])) {
    classes.push("hidden");
  }
  if (includesAny(words, ["spin", "spinner", "loading"])) {
    classes.push("animate-spin");
  }
  if (includesAny(words, ["active", "selected", "open", "current"])) {
    classes.push(toneClasses.selected);
  }

  const tone = toneFor(words);
  if (tone) {
    classes.push(tone);
  }

  return Array.from(new Set(classes.join(" ").split(/\s+/).filter(Boolean))).join(" ");
}

export function createVuiStyleMap<const TKeys extends readonly string[]>(
  keys: TKeys,
  options: VuiStyleMapOptions = {},
): Record<TKeys[number] | string, string> {
  const cache = new Map<string, string>();
  const keySet = new Set<string>(keys);
  const target: Record<string, string> = {};

  const resolveClass = (key: string) => {
    const override = options.overrides?.[key];
    if (override !== undefined) {
      const includeKeyClass = options.includeKeyClass ?? true;
      return [options.baseClassName, includeKeyClass ? key : "", override]
        .filter(Boolean)
        .join(" ");
    }
    const cached = cache.get(key);
    if (cached !== undefined) {
      return cached;
    }
    const includeKeyClass = options.includeKeyClass ?? true;
    const className = [options.baseClassName, includeKeyClass ? key : "", classesForKey(key), options.extensions?.[key]]
      .filter(Boolean)
      .join(" ");
    cache.set(key, className);
    return className;
  };

  for (const key of keys) {
    Object.defineProperty(target, key, {
      configurable: true,
      enumerable: true,
      get: () => resolveClass(key),
    });
  }

  return new Proxy(target, {
    get(currentTarget, property) {
      if (typeof property !== "string") {
        return Reflect.get(currentTarget, property);
      }
      if (property in currentTarget || keySet.has(property)) {
        return resolveClass(property);
      }
      return resolveClass(property);
    },
    getOwnPropertyDescriptor(currentTarget, property) {
      if (typeof property === "string" && !Reflect.has(currentTarget, property)) {
        Object.defineProperty(currentTarget, property, {
          configurable: true,
          enumerable: true,
          get: () => resolveClass(property),
        });
      }
      return Reflect.getOwnPropertyDescriptor(currentTarget, property);
    },
    ownKeys(currentTarget) {
      return Reflect.ownKeys(currentTarget);
    },
  }) as Record<TKeys[number] | string, string>;
}
