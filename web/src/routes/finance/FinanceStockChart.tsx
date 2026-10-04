import { useEffect, useMemo, useState } from "react";
import type { StockCandle, StockPeriod } from "../../api/financialMarket";
import { VSurface, VTabs } from "../../components/vui";
import { movingAverage, quoteNumber } from "./stockResearchModel";

export function FinanceStockChart({ candles, period, onPeriodChange, zh }: { candles: StockCandle[]; period: StockPeriod; onPeriodChange: (period: StockPeriod) => void; zh: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  useEffect(() => setHover(null), [candles]);
  const series = useMemo(() => ({ short: movingAverage(candles, 5), long: movingAverage(candles, 20) }), [candles]);
  const W = 1000, H = 310, left = 10, right = 65, top = 25, bottom = 238;
  const min = Math.min(...candles.map((item) => item.low)), max = Math.max(...candles.map((item) => item.high));
  const padding = Math.max((max - min) * .08, max * .001);
  const low = min - padding, high = max + padding;
  const y = (price: number) => top + (high - price) / (high - low) * (bottom - top);
  const spacing = (W - left - right) / Math.max(1, candles.length);
  const x = (index: number) => left + (index + .5) * spacing;
  const width = Math.max(1.5, spacing * .65);
  const volumeMax = Math.max(1, ...candles.map((item) => item.volumeLots));
  const active = hover === null ? candles.length - 1 : hover;
  const candle = candles[active];
  const path = (values: (number | null)[]) => values.flatMap((value, index) => value === null ? [] : [`${index === values.findIndex((v) => v !== null) ? "M" : "L"}${x(index)},${y(value)}`]).join(" ");
  return <VSurface tone="panel" padding="normal" className="min-w-0 border border-[var(--vui-border-subtle)] rounded-lg" ariaLabel={zh ? "股价与成交量" : "Price and volume"}>
    <div className="flex items-center justify-between gap-4 mb-3">
      <div className="flex items-center gap-4"><strong className="text-sm">{zh ? "价格走势" : "Price chart"}</strong><span className="text-xs text-[var(--fg-tertiary)]">{zh ? "前复权" : "Forward adjusted"}</span></div>
      <VTabs value={period} onValueChange={(value) => onPeriodChange(value as StockPeriod)} aria-label={zh ? "K 线周期" : "Chart period"} items={[{ id: "day", label: zh ? "日 K" : "Daily" }, { id: "week", label: zh ? "周 K" : "Weekly" }, { id: "month", label: zh ? "月 K" : "Monthly" }]} />
    </div>
    <div className="flex flex-wrap items-center gap-x-4 gap-y-1 text-xs tabular-nums text-[var(--fg-secondary)] min-h-6">
      <span>{candle?.date ?? "—"}</span><span>{zh ? "开" : "O"} {quoteNumber(candle?.open)}</span><span>{zh ? "高" : "H"} {quoteNumber(candle?.high)}</span><span>{zh ? "低" : "L"} {quoteNumber(candle?.low)}</span><span>{zh ? "收" : "C"} {quoteNumber(candle?.close)}</span>
      <span className="text-[var(--state-warning)]">MA5 {quoteNumber(series.short[active])}</span><span className="text-[var(--accent-cool)]">MA20 {quoteNumber(series.long[active])}</span>
    </div>
    {/* Financial chart geometry is SVG; all controls stay on the VUI API. */}
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-auto max-h-[330px] outline-none focus-visible:ring-2 focus-visible:ring-[var(--accent-cool)]" role="img" aria-label={zh ? "K 线与成交量，左右方向键查看数据" : "Candles and volume; use arrow keys to inspect"} tabIndex={0}
      onPointerMove={(event) => { const box = event.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(candles.length - 1, Math.floor(((event.clientX - box.left) / box.width * W - left) / spacing)))); }}
      onPointerLeave={() => setHover(null)} onKeyDown={(event) => { if (event.key === "ArrowLeft" || event.key === "ArrowRight") { event.preventDefault(); setHover(Math.max(0, Math.min(candles.length - 1, active + (event.key === "ArrowLeft" ? -1 : 1)))); } }}>
      <title>{zh ? "历史价格与成交量" : "Historical price and volume"}</title>
      {[0, 1, 2, 3, 4].map((tick) => { const price = high - (high - low) * tick / 4; return <g key={tick}><line x1={left} x2={W - right} y1={y(price)} y2={y(price)} stroke="var(--vui-border-subtle)" strokeDasharray="3 5" /><text x={W - right + 8} y={y(price) + 4} fill="var(--fg-tertiary)" fontSize="11">{price.toFixed(2)}</text></g>; })}
      {candles.map((item, index) => { const color = item.close >= item.open ? "var(--state-error)" : "var(--state-success)"; return <g key={item.date}><line x1={x(index)} x2={x(index)} y1={y(item.high)} y2={y(item.low)} stroke={color} /><rect x={x(index) - width / 2} y={Math.min(y(item.open), y(item.close))} width={width} height={Math.max(1, Math.abs(y(item.open) - y(item.close)))} fill={color} /><rect x={x(index) - width / 2} y={286 - item.volumeLots / volumeMax * 35} width={width} height={Math.max(1, item.volumeLots / volumeMax * 35)} fill={color} opacity=".55" /></g>; })}
      <path d={path(series.short)} stroke="var(--state-warning)" strokeWidth="1.5" fill="none" /><path d={path(series.long)} stroke="var(--accent-cool)" strokeWidth="1.5" fill="none" />
      {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={top} y2={288} stroke="var(--fg-tertiary)" strokeDasharray="3 3" /> : null}
      <text x={left} y={305} fontSize="11" fill="var(--fg-tertiary)">{candles[0]?.date}</text><text x={W - right} y={305} fontSize="11" textAnchor="end" fill="var(--fg-tertiary)">{candles.at(-1)?.date}</text>
    </svg>
    <div className="flex justify-between text-xs text-[var(--fg-tertiary)]"><span>{zh ? "成交量" : "Volume"} {quoteNumber(candle?.volumeLots, 0)} {zh ? "手" : "lots"}</span><span>{zh ? "1 手 = 100 股" : "1 lot = 100 shares"}</span></div>
  </VSurface>;
}
