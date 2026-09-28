/**
 * 样张区 —— 用生产真实 VUI 组件与令牌渲染，检验各基准下的协调性。
 * 四个样张区 + 派生字阶总览；全部字号走 --vui-font-* 派生档或声明的固定密度轴，
 * 不出现裸字号。固定例外区（画布/桌宠/终端）在切基准时必须纹丝不动。
 */
import { useState, type CSSProperties, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { VButton } from "../../../src/components/vui/primitives/VButton";
import { VChip } from "../../../src/components/vui/primitives/VChip";
import { VCheckbox } from "../../../src/components/vui/forms/VCheckbox";
import { VInput } from "../../../src/components/vui/forms/VInput";
import { VStringSelect } from "../../../src/components/vui/forms/VStringSelect";
import {
  VSettingsGroupCard,
  VSettingsRow,
} from "../../../src/components/vui/forms/VSettingsRow";
import { COPY, type Lang } from "./copy";
import { deriveLadder, FONT_SCALE_DEFAULT, type FontRungSpec } from "./fontScaleModel";
import { NumberStepper } from "./NumberStepper";

function SectionCard({
  title,
  children,
  note,
}: {
  title: ReactNode;
  children: ReactNode;
  note?: ReactNode;
}) {
  return (
    <section className="rounded-vui-panel border border-vui-border-subtle bg-vui-surface-panel">
      <header className="flex flex-wrap items-baseline justify-between gap-2 border-b border-vui-border-subtle px-4 py-3">
        <h2 className="text-vui-title font-semibold text-vui-fg-primary">{title}</h2>
        {note ? <div className="text-vui-xs text-vui-fg-tertiary">{note}</div> : null}
      </header>
      <div className="p-4">{children}</div>
    </section>
  );
}

/** 派生字阶总览：每档展示当前基准下的计算值（md=基准档高亮）。 */
function LadderOverview({ base, lang }: { base: number; lang: Lang }) {
  const ladder = deriveLadder(base);
  return (
    <SectionCard
      title={COPY.sectionLadder[lang]}
      note={lang === "zh" ? `基准 --vui-font-base = ${base}px` : `base --vui-font-base = ${base}px`}
    >
      <div className="grid gap-x-6 gap-y-1 sm:grid-cols-2">
        {ladder.map(({ spec, px }) => (
          <div
            key={spec.id}
            data-probe={spec.id === "md" ? "ladder-md" : undefined}
            className="flex items-baseline gap-3 border-b border-vui-border-hairline py-1.5 last:border-b-0"
            style={
              spec.id === "md"
                ? { background: "color-mix(in srgb, var(--accent-cool) 8%, transparent)" }
                : undefined
            }
          >
            <span
              className="w-24 shrink-0 text-vui-fg-primary tabular-nums"
              style={{ font: `600 ${px}px/1.2 var(--font-body)` }}
            >
              {spec.id} · {px}px
            </span>
            <span className="w-14 shrink-0 text-vui-xs text-vui-fg-tertiary tabular-nums">
              {spec.offsetPx >= 0 ? `+${spec.offsetPx}` : spec.offsetPx}
            </span>
            <span className="min-w-0 truncate text-vui-xs text-vui-fg-secondary">
              {lang === "zh" ? spec.usageZh : spec.usageEn}
            </span>
          </div>
        ))}
      </div>
    </SectionCard>
  );
}

/** 设置行样张：生产 VSettingsRow/VSettingsGroupCard + 三类控件。 */
function SettingsSample({ lang }: { lang: Lang }) {
  const [refreshSeconds, setRefreshSeconds] = useState(30);
  const [language, setLanguage] = useState("zh-CN");
  const [telemetry, setTelemetry] = useState(true);

  return (
    <SectionCard title={COPY.sectionSettings[lang]}>
      <VSettingsGroupCard>
        <VSettingsRow
          label={COPY.rowScaleHint[lang]}
          description={COPY.rowScaleHintDesc[lang]}
          testId="row-scale-hint"
        />
        <VSettingsRow
          label={<span data-probe="settings-label">{COPY.rowLanguage[lang]}</span>}
          description={COPY.rowLanguageDesc[lang]}
          control={
            <VStringSelect
              ariaLabel={COPY.rowLanguage[lang]}
              value={language}
              onValueChange={setLanguage}
              options={[
                { value: "zh-CN", label: "简体中文" },
                { value: "en-US", label: "English (US)" },
                { value: "ja-JP", label: "日本語" },
              ]}
            />
          }
        />
        <VSettingsRow
          label={COPY.rowTelemetry[lang]}
          description={COPY.rowTelemetryDesc[lang]}
          control={
            <VCheckbox
              aria-label={COPY.rowTelemetry[lang]}
              isSelected={telemetry}
              onChange={setTelemetry}
            />
          }
        />
        <VSettingsRow
          label={lang === "zh" ? "列表刷新间隔" : "List refresh interval"}
          description={COPY.rowCanvasFloorDesc[lang]}
          controlLayout="wide"
          control={
            <NumberStepper
              value={refreshSeconds}
              min={5}
              max={120}
              onChange={setRefreshSeconds}
              ariaLabel={lang === "zh" ? "列表刷新间隔" : "List refresh interval"}
              testId="sample-stepper"
            />
          }
          detail={
            <span className="text-vui-xs text-vui-fg-tertiary">
              {lang === "zh" ? "秒（5–120）" : "seconds (5–120)"}
            </span>
          }
        />
      </VSettingsGroupCard>
    </SectionCard>
  );
}

/** 会话样张：正文 chat 档、次级信息 xs 档、行内代码 sm 档 mono。 */
function ChatSample({ lang }: { lang: Lang }) {
  return (
    <SectionCard title={COPY.sectionChat[lang]}>
      <div className="grid gap-3">
        <div className="flex justify-end">
          <div className="max-w-[85%] rounded-vui-panel rounded-br-sm border border-vui-border-subtle bg-[color-mix(in_srgb,var(--accent-cool)_14%,var(--vui-surface-card))] px-4 py-3">
            <p
              className="text-vui-chat leading-[var(--vui-line-readable)] text-vui-fg-primary"
              data-probe="chat-body"
            >
              {COPY.chatUser[lang]}
            </p>
          </div>
        </div>
        <div className="flex justify-start">
          <div className="max-w-[85%] rounded-vui-panel rounded-bl-sm border border-vui-border-subtle bg-vui-surface-card px-4 py-3">
            <p className="text-vui-chat leading-[var(--vui-line-readable)] text-vui-fg-primary">
              {COPY.chatAssistant1[lang]}{" "}
              <code
                className="rounded-[var(--radius-control)] border border-vui-border-subtle bg-vui-surface-inset px-1.5 py-0.5 text-vui-sm text-vui-fg-primary"
                style={{ fontFamily: "var(--font-mono)" }}
              >
                {COPY.chatCodeInline}
              </code>
            </p>
            <ul className="mt-2 grid gap-1 pl-5">
              {COPY.chatAssistantBullets[lang].map((line) => (
                <li
                  key={line}
                  className="list-disc text-vui-chat leading-[var(--vui-line-normal)] text-vui-fg-secondary marker:text-vui-fg-tertiary"
                >
                  {line}
                </li>
              ))}
            </ul>
            <div className="mt-2 text-vui-xs text-vui-fg-tertiary">{COPY.chatMeta[lang]}</div>
          </div>
        </div>
        <div className="flex justify-start">
          <span className="rounded-full border border-vui-border-subtle bg-vui-surface-inset px-2.5 py-1 text-vui-2xs text-vui-fg-tertiary">
            meta 2xs · {COPY.chatUser[lang].slice(0, 18)}…
          </span>
        </div>
      </div>
    </SectionCard>
  );
}

/** 密集操作样张：面包屑 / chip / 按钮组 / 输入框。 */
function DenseOpsSample({ lang }: { lang: Lang }) {
  return (
    <SectionCard title={COPY.sectionDense[lang]}>
      <div className="grid gap-4">
        <nav className="flex items-center gap-1 text-vui-xs text-vui-fg-tertiary">
          <span>{COPY.breadcrumbRoot[lang]}</span>
          <ChevronRight className="h-3.5 w-3.5" />
          <span>{COPY.breadcrumbMid[lang]}</span>
          <ChevronRight className="h-3.5 w-3.5" />
          <span className="text-vui-fg-primary" data-probe="dense-breadcrumb">
            {COPY.breadcrumbLeaf[lang]}
          </span>
        </nav>
        <div className="flex flex-wrap items-center gap-2">
          <VChip tone="neutral">{COPY.chipStable[lang]}</VChip>
          <VChip tone="accent">{COPY.chipBeta[lang]}</VChip>
          <VChip tone="success">{COPY.chipDone[lang]}</VChip>
          <VChip tone="warning">{COPY.chipPending[lang]}</VChip>
          <VChip tone="danger">{COPY.chipFailed[lang]}</VChip>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <VButton variant="primary">{COPY.btnPrimary[lang]}</VButton>
          <VButton variant="secondary">{COPY.btnSecondary[lang]}</VButton>
          <VButton variant="ghost">{COPY.btnGhost[lang]}</VButton>
          <VButton variant="danger">{COPY.btnDanger[lang]}</VButton>
        </div>
        <VInput
          placeholder={COPY.denseInputPlaceholder[lang]}
          aria-label={COPY.denseInputPlaceholder[lang]}
          data-probe="dense-input"
          className="max-w-sm"
        />
      </div>
    </SectionCard>
  );
}

/**
 * 固定例外对照：画布子阶梯（canvas-2xs..xl=9–15px）、桌宠状态（固定 px）、
 * 终端（13px mono）。全部不引用 --vui-font-base，切基准时纹丝不动。
 */
function FixedExceptionsSample({ lang }: { lang: Lang }) {
  return (
    <SectionCard title={COPY.sectionFixed[lang]} note={COPY.fixedCaption[lang]}>
      <div className="grid gap-4 lg:grid-cols-3">
        {/* 画布节点小样 —— 阶梯同构 WorkflowNodeChrome：kicker/标题/副题/徽章/meta。 */}
        <div className="rounded-vui-control border border-vui-border-subtle bg-vui-surface-card p-3">
          <div className="text-vui-fg-tertiary" style={{ fontSize: "var(--vui-font-canvas-2xs)", letterSpacing: "var(--vui-tracking-label)" }}>
            {COPY.canvasKicker[lang]}
          </div>
          <div
            className="mt-0.5 font-bold text-vui-fg-primary"
            style={{ fontSize: "var(--vui-font-canvas-xl)", letterSpacing: "-0.02em" }}
            data-probe="canvas-title"
          >
            {COPY.canvasTitle[lang]}
          </div>
          <div className="text-vui-fg-secondary" style={{ fontSize: "var(--vui-font-canvas-md)" }}>
            {COPY.canvasSubtitle[lang]}
          </div>
          <div className="mt-2 flex flex-wrap items-center gap-1">
            <span
              className="inline-flex items-center rounded-md border border-vui-border-subtle bg-vui-surface-row px-1.5 py-0.5 font-semibold text-vui-fg-secondary"
              style={{ fontSize: "var(--vui-font-canvas-xs)" }}
            >
              {COPY.canvasBadge[lang]}
            </span>
            <span
              className="inline-flex items-center rounded-full border border-[color-mix(in_srgb,var(--accent-cool)_30%,var(--vui-border-subtle))] bg-[color-mix(in_srgb,var(--accent-cool)_8%,transparent)] px-1.5 py-0.5 font-semibold text-[var(--accent-cool)]"
              style={{ fontSize: "var(--vui-font-canvas-xs)" }}
            >
              {COPY.canvasEmphasis[lang]}
            </span>
          </div>
          <div className="mt-1.5 text-vui-fg-tertiary" style={{ fontSize: "var(--vui-font-canvas-sm)" }}>
            {COPY.canvasMeta[lang]}
          </div>
        </div>

        {/* 桌宠状态小样 —— 照 desktop-pet.tailwind.css 的 .desktop-pet-status（11px）与副行（9px）。 */}
        <div className="flex flex-col items-center justify-center gap-2 rounded-vui-control border border-vui-border-subtle bg-vui-surface-card p-3">
          <span className="text-vui-fg-tertiary" style={{ fontSize: 10 }}>
            {COPY.petHeader[lang]}
          </span>
          <span
            className="inline-flex max-w-[214px] items-center gap-1.5 overflow-hidden whitespace-nowrap rounded-full border px-[9px] py-[5px]"
            style={{
              fontSize: 11,
              lineHeight: 1,
              borderColor: "rgb(var(--vui-pet-accent-rgb) / 28%)",
              background: "var(--vui-pet-panel)",
              color: "var(--vui-pet-fg)",
              boxShadow: "var(--vui-pet-shadow-status)",
            }}
            data-probe="pet-status"
          >
            <span
              className="h-[7px] w-[7px] shrink-0 rounded-full"
              style={{ background: "var(--vui-pet-accent)", boxShadow: "0 0 12px rgb(var(--vui-pet-accent-rgb) / 70%)" }}
            />
            {COPY.petStatus[lang]}
          </span>
          <span style={{ fontSize: 9, lineHeight: 1, color: "var(--vui-pet-fg-meta)" }}>
            {COPY.petSub[lang]}
          </span>
        </div>

        {/* 终端小样 —— xterm 13px 固定。 */}
        <div className="rounded-vui-control border border-vui-border-subtle bg-vui-surface-inset p-3" style={{ colorScheme: "dark" }}>
          <div style={{ font: `13px/1.6 var(--font-mono)`, color: "var(--vui-pet-tone-completed)" }} data-probe="terminal-line">
            {COPY.terminalLine}
          </div>
          <div style={{ font: `13px/1.6 var(--font-mono)`, color: "var(--fg-secondary)" }}>
            {COPY.terminalOutput}
          </div>
        </div>
      </div>
    </SectionCard>
  );
}

/**
 * 完整样张。基准作用域由祖先的 --vui-font-base 决定（单栏=根、AB=各栏内联），
 * 本组件自身不感知基准值，只消费派生档。
 */
export function SampleSheet({ base, lang }: { base: number; lang: Lang }) {
  void base;
  return (
    <div className="grid gap-4">
      <LadderOverview base={base} lang={lang} />
      <SettingsSample lang={lang} />
      <ChatSample lang={lang} />
      <DenseOpsSample lang={lang} />
      <FixedExceptionsSample lang={lang} />
    </div>
  );
}

/** 兼容旧引用风格的类型出口（保留给 AB 栏头使用）。 */
export type { FontRungSpec };
export const AB_BASE_PANE_STYLE: CSSProperties = { "--vui-font-base": `${FONT_SCALE_DEFAULT}px` } as CSSProperties;
