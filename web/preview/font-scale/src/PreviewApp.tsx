/**
 * 单一字号派生字阶预览 —— 隔离预览应用（不进生产路由）。
 *
 * - 顶部基准切换器：ZCode FontSizeInput 步进器（−/+ + 数字输入，step 1，
 *   硬钳制 14–18，默认 16）+ 14/16/17/18 快捷档；切换即整页生效（写
 *   documentElement 的 --vui-font-base，fontScaleTokens.css 的 calc 派生随之联动）。
 * - A/B 对拍：?mode=ab 时左右分栏同屏渲染 16px 与当前所选档（各栏内联
 *   --vui-font-base 作用域）。
 * - 深链：?base=14..18&mode=ab&theme=dark|light；UI 切换回写地址栏（可分享）。
 * - 底部如实标注：派生式为预览本地副本；画布/桌宠/终端为固定例外；生产钳制 14–18。
 *
 * UI 只用 web/src/components/vui 的 V* 与 --vui-* 令牌；不引第二设计系统。
 */
import { useCallback, useEffect, useState } from "react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { COPY, type Lang } from "./copy";
import {
  buildDeepLink,
  clampBase,
  FONT_SCALE_DEFAULT,
  FONT_SCALE_MAX,
  FONT_SCALE_MIN,
  QUICK_BASES,
  readBootState,
  type PreviewMode,
} from "./fontScaleModel";
import { NumberStepper } from "./NumberStepper";
import { SampleSheet } from "./Samples";

export function PreviewApp() {
  // 深链初始态：一次读入，保证首屏即现目标态（index.html 已提前落 base 防 FOUC）。
  const [boot] = useState(() => readBootState(window.location.search));
  const [base, setBase] = useState(() => clampBase(boot.base));
  const [mode, setMode] = useState<PreviewMode>(boot.mode);
  const [lang, setLang] = useState<Lang>("zh");

  // 基准/模式变化 → 同步 documentElement 作用域与深链（replaceState，不刷页）。
  useEffect(() => {
    const root = document.documentElement;
    root.style.setProperty("--vui-font-base", `${base}px`);
    root.setAttribute("data-font-base", String(base));
    const link = buildDeepLink(base, mode);
    window.history.replaceState(null, "", link);
  }, [base, mode]);

  const changeBase = useCallback((next: number) => {
    setBase(clampBase(next));
  }, []);

  const abActive = mode === "ab";
  const abSame = base === FONT_SCALE_DEFAULT;

  return (
    <div className="min-h-screen bg-vui-bg-canvas text-vui-fg-primary">
      {/* 顶部：标题 + 基准切换器 + 快捷档 + 模式/语言 */}
      <header className="sticky top-0 z-20 border-b border-vui-border-subtle bg-vui-surface-panel/95 backdrop-blur">
        <div className="mx-auto flex max-w-[1180px] flex-wrap items-center gap-x-6 gap-y-3 px-5 py-3">
          <div className="min-w-0">
            <h1 className="text-vui-title font-semibold leading-tight">{COPY.pageTitle[lang]}</h1>
            <p className="mt-0.5 text-vui-xs text-vui-fg-tertiary">{COPY.pageSub[lang]}</p>
          </div>
          <div className="ms-auto flex flex-wrap items-center gap-x-4 gap-y-2">
            <div className="flex items-center gap-2">
              <span className="text-vui-sm text-vui-fg-secondary">{COPY.baseLabel[lang]}</span>
              <NumberStepper
                value={base}
                min={FONT_SCALE_MIN}
                max={FONT_SCALE_MAX}
                onChange={changeBase}
                ariaLabel={COPY.baseLabel[lang]}
                testId="base-stepper"
              />
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-vui-sm text-vui-fg-secondary">{COPY.quickLabel[lang]}</span>
              {QUICK_BASES.map((candidate) => (
                <VButton
                  key={candidate}
                  variant={candidate === base ? "primary" : "secondary"}
                  density="compact"
                  data-testid={`quick-${candidate}`}
                  aria-pressed={candidate === base}
                  onClick={() => changeBase(candidate)}
                >
                  {candidate}
                </VButton>
              ))}
            </div>
            <VButton
              variant={abActive ? "primary" : "secondary"}
              density="compact"
              data-testid="ab-toggle"
              onClick={() => setMode((current) => (current === "ab" ? "single" : "ab"))}
            >
              {abActive ? COPY.abExit[lang] : COPY.abToggle[lang]}
            </VButton>
            <VButton
              variant="ghost"
              density="compact"
              data-testid="lang-toggle"
              onClick={() => setLang((current) => (current === "zh" ? "en" : "zh"))}
            >
              {COPY.langToggle[lang]}
            </VButton>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1180px] px-5 py-5">
        {abActive ? (
          <div className="grid gap-4 xl:grid-cols-2">
            {/* 左栏固定 16px（现网基准）；右栏当前所选。各栏内联作用域。 */}
            <div className="grid gap-3 content-start rounded-vui-panel border border-vui-border-subtle p-3">
              <div className="flex items-center justify-between gap-2 px-1">
                <span className="text-vui-sm font-semibold">{COPY.abLeftTitle[lang]}</span>
                <span className="text-vui-xs text-vui-fg-tertiary tabular-nums">16px</span>
              </div>
              <div className="font-scale-scope" style={{ "--vui-font-base": "16px" } as React.CSSProperties}>
                <SampleSheet base={FONT_SCALE_DEFAULT} lang={lang} />
              </div>
            </div>
            <div className="grid gap-3 content-start rounded-vui-panel border border-[color-mix(in_srgb,var(--accent-cool)_45%,var(--vui-border-subtle))] p-3">
              <div className="flex items-center justify-between gap-2 px-1">
                <span className="text-vui-sm font-semibold">{COPY.abRightTitle[lang]}</span>
                <span className="text-vui-xs text-vui-fg-tertiary tabular-nums">{base}px</span>
              </div>
              {abSame ? (
                <div className="px-1 text-vui-xs text-vui-fg-tertiary">{COPY.abSameHint[lang]}</div>
              ) : null}
              <div className="font-scale-scope" style={{ "--vui-font-base": `${base}px` } as React.CSSProperties}>
                <SampleSheet base={base} lang={lang} />
              </div>
            </div>
          </div>
        ) : (
          <SampleSheet base={base} lang={lang} />
        )}

        {/* 底部如实标注 */}
        <footer className="mt-6 rounded-vui-panel border border-vui-border-subtle bg-vui-surface-panel px-4 py-3">
          <ul className="grid gap-1.5 text-vui-xs leading-relaxed text-vui-fg-tertiary">
            <li>· {COPY.footerDerived[lang]}</li>
            <li>· {COPY.footerFixed[lang]}</li>
            <li>· {COPY.footerClamp[lang]}</li>
            <li>· {COPY.footerZeroDrift[lang]}</li>
          </ul>
        </footer>
      </main>
    </div>
  );
}
