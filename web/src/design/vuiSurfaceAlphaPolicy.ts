/**
 * Policy for color-mix(...) that references --vui-surface-* tokens.
 *
 * Structural product boards must be opaque recipes (see vuiSurfaceRecipes).
 * Only state tints, glass/overlay roles, and a short intentional soft-layer
 * allowlist may mix surface tokens with transparency or foreign colors.
 */

export type VuiSurfaceAlphaRole =
  | "state-tint"
  | "glass-overlay"
  | "chat-soft-layer"
  | "surface-blend"
  | "token-definition"
  | "forbidden-structure-wash";

export type VuiSurfaceAlphaHit = {
  file: string;
  mix: string;
  role: VuiSurfaceAlphaRole;
  allowed: boolean;
};

/** Paths relative to web/src that define theme tokens (not page chrome). */
const TOKEN_DEFINITION_PATH_RE =
  /(^|\/)(design\/tokens\.css|design\/workbench-shell\.css|design\/codeMirrorTheme\.ts|design\/vuiSurfaceRecipes\.ts|design\/vuiSurfaceAlphaPolicy\.ts)$/;

/**
 * VUI primitive / renderer soft materials (dialog, tooltip, state surface).
 * Page style maps must not invent new surface+transparent washes.
 */
const VUI_COMPONENT_SOFT_PATH_RE = /(^|\/)components\/vui\//;

/**
 * Intentional soft layers: path fragment + substring that must appear on the
 * same class string (or nearby source). Used only when first operand is a
 * surface token mixed with transparent (otherwise would be forbidden).
 */
const CHAT_SOFT_LAYER_ALLOW: ReadonlyArray<{ pathIncludes: string; sourceIncludes: string }> = [
  { pathIncludes: "ChatCodingRoute.styles.ts", sourceIncludes: "centerSurface" },
  { pathIncludes: "ConversationView.styles.ts", sourceIncludes: "composer" },
  { pathIncludes: "SessionContextMenu.styles.ts", sourceIncludes: "sessionContextMenu" },
];

const STATE_TINT_FIRST_OPS = new Set([
  "--accent-cool",
  "--accent-cool-2",
  "--accent-warm",
  "--accent-warm-2",
  "--accent-primary",
  "--accent-danger",
  "--accent",
  "--state-error",
  "--state-success",
  "--state-warning",
  "--state-danger",
  "--danger",
  "--success",
  "--warning",
  "--fg-primary",
]);

const SURFACE_TOKEN_RE = /--vui-surface-[a-z0-9-]+/g;
const FIRST_VAR_RE = /var\(\s*(--[a-z0-9-]+)\s*\)/i;

export function extractColorMixCalls(source: string): string[] {
  const out: string[] = [];
  let i = 0;
  while (i < source.length) {
    const j = source.indexOf("color-mix(", i);
    if (j < 0) break;
    let depth = 0;
    let k = j;
    while (k < source.length) {
      if (source.startsWith("color-mix(", k)) {
        depth += 1;
        k += "color-mix(".length;
        continue;
      }
      const ch = source[k];
      if (ch === "(") {
        depth += 1;
        k += 1;
        continue;
      }
      if (ch === ")") {
        depth -= 1;
        if (depth === 0) {
          out.push(source.slice(j, k + 1));
          k += 1;
          break;
        }
        k += 1;
        continue;
      }
      k += 1;
    }
    i = k;
  }
  return out.filter((mix) => /--vui-surface-/.test(mix));
}

function normalizeMix(mix: string): string {
  return mix.replace(/\s+/g, "");
}

function firstCssVar(mix: string): string | null {
  const m = FIRST_VAR_RE.exec(mix);
  return m ? m[1] : null;
}

function hasTransparent(mix: string): boolean {
  return /transparent/i.test(mix);
}

function isSurfaceToken(token: string | null): boolean {
  return Boolean(token && token.startsWith("--vui-surface-"));
}

/**
 * Classify a single color-mix that contains at least one --vui-surface-* token.
 */
export function classifyVuiSurfaceColorMix(
  mix: string,
  filePath: string,
  source: string,
): VuiSurfaceAlphaHit {
  const file = filePath.replace(/\\/g, "/");
  const roleBase = (): VuiSurfaceAlphaRole => {
    if (TOKEN_DEFINITION_PATH_RE.test(file)) {
      return "token-definition";
    }

    const first = firstCssVar(mix);
    if (first && STATE_TINT_FIRST_OPS.has(first)) {
      return "state-tint";
    }

    // glass / overlay roles
    if (
      /--vui-surface-glass/.test(mix)
      || /--vui-surface-overlay/.test(mix)
      || /--vui-surface-popover/.test(mix)
    ) {
      return "glass-overlay";
    }

    // Intentional chat soft layers (surface + transparent)
    if (isSurfaceToken(first) && hasTransparent(mix)) {
      for (const rule of CHAT_SOFT_LAYER_ALLOW) {
        if (file.includes(rule.pathIncludes) && source.includes(rule.sourceIncludes)) {
          return "chat-soft-layer";
        }
      }
      if (VUI_COMPONENT_SOFT_PATH_RE.test(file)) {
        return "glass-overlay";
      }
      return "forbidden-structure-wash";
    }

    // Surface blended with another solid (panel/workspace/row/control) — allowed soft elevation
    if (isSurfaceToken(first) && !hasTransparent(mix)) {
      return "surface-blend";
    }

    // Second/third operand only surface with state first already handled.
    // Accent-like keywords in mix even if first parse failed (underscore variants)
    if (
      /var\(\s*--(accent|state-|danger|success|warning)/i.test(mix)
      && /--vui-surface-/.test(mix)
    ) {
      return "state-tint";
    }

    if (isSurfaceToken(first) && hasTransparent(mix)) {
      return "forbidden-structure-wash";
    }

    return "surface-blend";
  };

  const role = roleBase();
  const allowed = role !== "forbidden-structure-wash";
  return { file, mix: normalizeMix(mix), role, allowed };
}

export function scanSourceForVuiSurfaceAlpha(
  source: string,
  filePath: string,
): VuiSurfaceAlphaHit[] {
  return extractColorMixCalls(source)
    .filter((mix) => /--vui-surface-/.test(mix))
    .map((mix) => classifyVuiSurfaceColorMix(mix, filePath, source));
}

export function isStyleMapPath(filePath: string): boolean {
  const f = filePath.replace(/\\/g, "/");
  return f.endsWith(".styles.ts") || f.endsWith(".styles.tsx");
}
