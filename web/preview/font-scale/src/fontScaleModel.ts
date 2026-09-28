/**
 * 单一字号派生字阶 —— 预览的数学模型（与 fontScaleTokens.css 一一对应）。
 *
 * 公式：derived(rung, base) = pxAt16(rung) + (base − 16)
 * CSS 形态：--vui-font-<rung> = calc(var(--vui-font-base) + offsetPx)，其中
 * offsetPx = pxAt16 − 16。base=16 时逐档等于生产 tokens.css 现值（零漂移）。
 *
 * 钳制：base ∈ [14, 18]（控件高度 30px 固定，再大会挤压）。
 * 固定例外：画布/桌宠/终端不在本模型内——它们不随 base 变。
 */

export const FONT_SCALE_MIN = 14;
export const FONT_SCALE_MAX = 18;
export const FONT_SCALE_DEFAULT = 16;
export const BASE_STEP = 1;

export const QUICK_BASES = [14, 16, 17, 18] as const;

export type FontRungId =
  | "micro-9"
  | "micro-10"
  | "micro-11"
  | "2xs"
  | "micro-13"
  | "xs"
  | "sm"
  | "md"
  | "chat"
  | "lg"
  | "title"
  | "xl";

export type FontRungSpec = {
  id: FontRungId;
  /** base=16 时的现值（= 生产 tokens.css 的 rem × 16）。 */
  pxAt16: number;
  /** CSS calc 偏移 = pxAt16 − 16。 */
  offsetPx: number;
  usageZh: string;
  usageEn: string;
};

function rung(id: FontRungId, pxAt16: number, usageZh: string, usageEn: string): FontRungSpec {
  return { id, pxAt16, offsetPx: pxAt16 - 16, usageZh, usageEn };
}

/** 主字阶全档清单（顺序与生产 tokens.css 一致）。 */
export const FONT_RUNGS: readonly FontRungSpec[] = [
  rung("micro-9", 9, "微字元信息，徽标/眉题（少用）", "micro meta, badge/eyebrow (rare)"),
  rung("micro-10", 10, "微字元信息", "micro meta"),
  rung("micro-11", 11, "微字元信息", "micro meta"),
  rung("2xs", 12, "密集元信息（少用）", "dense meta (rare)"),
  rung("micro-13", 13, "微字元信息 / 标签", "micro meta / label"),
  rung("xs", 14, "说明 / chip / 工具栏", "caption / chip / toolbar"),
  rung("sm", 15, "控件 / 列表次级", "control / list secondary"),
  rung("md", 16, "正文默认（基准档）", "body default (the base rung)"),
  rung("chat", 17, "会话可读正文", "conversation readable"),
  rung("lg", 18, "强调正文 / 空态", "emphasis body / empty states"),
  rung("title", 19, "区块 / 路由标题", "section / route title"),
  rung("xl", 22, "页面标题（少用，例外刻度 +6）", "page title (rare, exception tick +6)"),
];

/** 基准钳制：越界归到最近边界，非有限值归默认。 */
export function clampBase(value: number): number {
  if (!Number.isFinite(value)) {
    return FONT_SCALE_DEFAULT;
  }
  return Math.min(FONT_SCALE_MAX, Math.max(FONT_SCALE_MIN, Math.round(value)));
}

/** 步进（ZCode FontSizeInput / stepNumberValue 模式）：step 1 + min/max 硬钳制。 */
export function stepBase(current: number, direction: 1 | -1): number {
  const next = current + direction * BASE_STEP;
  return clampBase(next);
}

/** 派生公式：与 fontScaleTokens.css 的 calc(基准 + offsetPx) 逐档等价。 */
export function derivedPx(spec: FontRungSpec, base: number): number {
  return spec.pxAt16 + (base - 16);
}

/** 某基准下的完整派生表。 */
export function deriveLadder(base: number): ReadonlyArray<{ spec: FontRungSpec; px: number }> {
  const clamped = clampBase(base);
  return FONT_RUNGS.map((spec) => ({ spec, px: derivedPx(spec, clamped) }));
}

export type PreviewMode = "single" | "ab";
export type PreviewTheme = "dark" | "light";

export type PreviewBoot = {
  base: number;
  mode: PreviewMode;
  theme: PreviewTheme | null;
};

/** 深链解析：?base=14..18（越界钳制）&mode=ab&theme=dark|light。 */
export function readBootState(search: string): PreviewBoot {
  const params = new URLSearchParams(search);
  const rawBase = params.get("base");
  const base = rawBase === null ? FONT_SCALE_DEFAULT : clampBase(Number(rawBase));
  const mode: PreviewMode = params.get("mode") === "ab" ? "ab" : "single";
  const themeParam = params.get("theme");
  const theme: PreviewTheme | null =
    themeParam === "dark" || themeParam === "light" ? themeParam : null;
  return { base, mode, theme };
}

/** 把当前态同步回深链（保持可分享；mode=single 时省略）。 */
export function buildDeepLink(base: number, mode: PreviewMode): string {
  const params = new URLSearchParams();
  if (base !== FONT_SCALE_DEFAULT) {
    params.set("base", String(base));
  }
  if (mode === "ab") {
    params.set("mode", "ab");
  }
  const query = params.toString();
  const path = window.location.pathname;
  return query ? `${path}?${query}` : path;
}
