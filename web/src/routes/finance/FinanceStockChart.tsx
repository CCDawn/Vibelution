import styles from "./FinanceStockChart.styles";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import type { StockCandle, StockPeriod } from "../../api/financialMarket";
import { VIconButton, VStateSurface, VSurface, VTabs } from "../../components/vui";
import { quoteNumber } from "./stockResearchModel";
import { financeChartIndicators } from "./financeChartIndicators";

type Indicator = "ma" | "boll" | "macd" | "rsi";

export function FinanceStockChart({ candles, period, onPeriodChange, zh }: { candles: StockCandle[]; period: StockPeriod; onPeriodChange: (period: StockPeriod) => void; zh: boolean }) {
  const [hover, setHover] = useState<number | null>(null);
  const [indicator, setIndicator] = useState<Indicator>("ma"), [range, setRange] = useState("all");
  const [offset, setOffset] = useState(0), [announcement, setAnnouncement] = useState("");
  const readoutId = useId(), drag = useRef<{ x: number; offset: number } | null>(null);
  useEffect(() => { setHover(null); setAnnouncement(""); }, [candles, range, offset]);
  const series = useMemo(() => financeChartIndicators(candles), [candles]);
  const size = range === "all" ? candles.length : Math.min(Number(range), candles.length);
  const maxOffset = Math.max(0, candles.length - size), effectiveOffset = Math.min(offset, maxOffset);
  const end = candles.length - effectiveOffset, start = Math.max(0, end - size), visible = candles.slice(start, end);
  const auxiliary = indicator === "macd" || indicator === "rsi";
  const W = 1000, H = auxiliary ? 395 : 310, left = 10, right = 65, top = 25, bottom = 238;
  const overlay = indicator === "boll" ? [series.upper, series.long, series.lower] : indicator === "ma" ? [series.short, series.long] : [];
  const prices = [...visible.flatMap((item) => [item.low, item.high]), ...overlay.flatMap((values) => values.slice(start, end).filter((value): value is number => value !== null))];
  const min = Math.min(...prices), max = Math.max(...prices);
  const padding = Math.max((max - min) * .08, Math.abs(max) * .001, .01);
  const low = min - padding, high = max + padding;
  const y = (price: number) => top + (high - price) / (high - low) * (bottom - top);
  const spacing = (W - left - right) / Math.max(1, visible.length);
  const x = (index: number) => left + (index + .5) * spacing;
  const width = Math.max(1.5, spacing * .65);
  const volumeMax = Math.max(1, ...visible.map((item) => item.volumeLots));
  const active = start + (hover === null ? visible.length - 1 : Math.min(hover, visible.length - 1));
  const candle = candles[active];
  const path = (values: (number | null)[], scale = y) => {
    let connected = false;
    return values.slice(start, end).map((value, index) => {
      if (value === null) { connected = false; return ""; }
      const command = connected ? "L" : "M"; connected = true;
      return `${command}${x(index)},${scale(value)}`;
    }).join(" ");
  };
  const oscillator = indicator === "rsi" ? [series.rsi] : [series.dif, series.dea, series.histogram];
  const oscillatorValues = oscillator.flatMap((values) => values.slice(start, end).filter((value): value is number => value !== null));
  const oscMin = indicator === "rsi" ? 0 : Math.min(0, ...oscillatorValues), oscMax = indicator === "rsi" ? 100 : Math.max(0, ...oscillatorValues);
  const oscY = (value: number) => 355 - (value - oscMin) / (oscMax - oscMin || 1) * 55;
  const move = (delta: number) => setOffset(Math.max(0, Math.min(maxOffset, effectiveOffset + delta)));
  if (!visible.length) return <VStateSurface tone="empty" title={zh ? "暂无 K 线数据" : "No candle data"} />;
  return <VSurface tone="panel" padding="normal" className={styles.surface} ariaLabel={zh ? "股价与成交量" : "Price and volume"}>
    <div className={styles.heading}>
      <div className={styles.titleRow}><strong className={styles.title}>{zh ? "价格走势" : "Price chart"}</strong><span className={styles.adjustment}>{zh ? "前复权" : "Forward adjusted"}</span></div>
      <VTabs value={period} onValueChange={(value) => onPeriodChange(value as StockPeriod)} aria-label={zh ? "K 线周期" : "Chart period"} items={[{ id: "day", label: zh ? "日 K" : "Daily" }, { id: "week", label: zh ? "周 K" : "Weekly" }, { id: "month", label: zh ? "月 K" : "Monthly" }]} />
    </div>
    <div className={styles.controls}>
      <VTabs value={indicator} onValueChange={(value) => setIndicator(value as Indicator)} aria-label={zh ? "技术指标" : "Indicators"} items={[{ id: "ma", label: "MA" }, { id: "boll", label: "BOLL" }, { id: "macd", label: "MACD" }, { id: "rsi", label: "RSI" }]} />
      <div className={styles.rangeControls}><VTabs value={range} onValueChange={(value) => { setRange(value); setOffset(0); }} aria-label={zh ? "显示范围" : "Visible range"} items={[{ id: "30", label: zh ? "30 根" : "30 bars" }, { id: "60", label: zh ? "60 根" : "60 bars" }, { id: "all", label: zh ? "全部" : "All" }]} /><VIconButton label={zh ? "查看更早 K 线" : "Earlier candles"} icon={<ChevronLeft size={14} />} isDisabled={!maxOffset || effectiveOffset === maxOffset} onPress={() => move(Math.max(1, Math.round(size / 3)))} /><VIconButton label={zh ? "查看较新 K 线" : "Newer candles"} icon={<ChevronRight size={14} />} isDisabled={effectiveOffset === 0} onPress={() => move(-Math.max(1, Math.round(size / 3)))} /></div>
    </div>
    <div className={styles.legend}>
      <span>{candle?.date ?? "—"}</span><span>{zh ? "开" : "O"} {quoteNumber(candle?.open)}</span><span>{zh ? "高" : "H"} {quoteNumber(candle?.high)}</span><span>{zh ? "低" : "L"} {quoteNumber(candle?.low)}</span><span>{zh ? "收" : "C"} {quoteNumber(candle?.close)}</span>
      {indicator === "ma" ? <><span className={styles.shortAverage}>MA5 {quoteNumber(series.short[active])}</span><span className={styles.longAverage}>MA20 {quoteNumber(series.long[active])}</span></> : indicator === "boll" ? <><span className={styles.shortAverage}>BOLL20 {quoteNumber(series.long[active])}</span><span>{zh ? "上 / 下" : "U / L"} {quoteNumber(series.upper[active])} / {quoteNumber(series.lower[active])}</span></> : indicator === "rsi" ? <span>RSI14 {quoteNumber(series.rsi[active])}</span> : <span>DIF {quoteNumber(series.dif[active])} · DEA {quoteNumber(series.dea[active])} · MACD {quoteNumber(series.histogram[active])}</span>}
    </div>
    {/* Financial chart geometry is SVG; all controls stay on the VUI API. */}
    <svg viewBox={`0 0 ${W} ${H}`} className={styles.chart} role="img" aria-label={zh ? "K 线与成交量，方向键查看数据，拖动平移" : "Candles and volume; arrow keys inspect data, drag to pan"} aria-describedby={readoutId} tabIndex={0}
      onPointerDown={(event) => { if (event.button !== 0 || !maxOffset) return; drag.current = { x: event.clientX, offset: effectiveOffset }; event.currentTarget.setPointerCapture(event.pointerId); }}
      onPointerMove={(event) => {
        if (drag.current) { setOffset(Math.max(0, Math.min(maxOffset, drag.current.offset + Math.round((event.clientX - drag.current.x) / event.currentTarget.getBoundingClientRect().width * W / spacing)))); return; }
        const box = event.currentTarget.getBoundingClientRect(); setHover(Math.max(0, Math.min(visible.length - 1, Math.floor(((event.clientX - box.left) / box.width * W - left) / spacing))));
      }}
      onPointerUp={(event) => { drag.current = null; if (event.currentTarget.hasPointerCapture(event.pointerId)) event.currentTarget.releasePointerCapture(event.pointerId); }} onPointerCancel={() => { drag.current = null; }} onLostPointerCapture={() => { drag.current = null; }}
      onPointerLeave={() => { if (!drag.current) setHover(null); }} onKeyDown={(event) => {
        if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
        event.preventDefault();
        if (event.shiftKey) { move(event.key === "ArrowLeft" ? 1 : -1); return; }
        const next = Math.max(0, Math.min(visible.length - 1, active - start + (event.key === "ArrowLeft" ? -1 : 1)));
        const row = visible[next]; setHover(next);
        setAnnouncement(`${row.date}，${zh ? "开" : "Open"} ${quoteNumber(row.open)}，${zh ? "高" : "High"} ${quoteNumber(row.high)}，${zh ? "低" : "Low"} ${quoteNumber(row.low)}，${zh ? "收" : "Close"} ${quoteNumber(row.close)}`);
      }}>
      <title>{zh ? "历史价格与成交量" : "Historical price and volume"}</title>
      {[0, 1, 2, 3, 4].map((tick) => { const price = high - (high - low) * tick / 4; return <g key={tick}><line x1={left} x2={W - right} y1={y(price)} y2={y(price)} stroke="var(--vui-border-subtle)" strokeDasharray="3 5" /><text x={W - right + 8} y={y(price) + 4} fill="var(--fg-tertiary)" fontSize="11">{price.toFixed(2)}</text></g>; })}
      {visible.map((item, index) => { const color = item.close >= item.open ? "var(--state-error)" : "var(--state-success)"; return <g key={item.date}><line x1={x(index)} x2={x(index)} y1={y(item.high)} y2={y(item.low)} stroke={color} /><rect x={x(index) - width / 2} y={Math.min(y(item.open), y(item.close))} width={width} height={Math.max(1, Math.abs(y(item.open) - y(item.close)))} fill={color} /><rect x={x(index) - width / 2} y={286 - item.volumeLots / volumeMax * 35} width={width} height={Math.max(1, item.volumeLots / volumeMax * 35)} fill={color} opacity=".55" /></g>; })}
      {overlay.map((values, index) => <path key={index} d={path(values)} stroke={index === 1 ? "var(--accent-cool)" : "var(--state-warning)"} strokeWidth="1.5" fill="none" />)}
      {auxiliary ? <>
        <line x1={left} x2={W - right} y1={oscY(indicator === "rsi" ? 50 : 0)} y2={oscY(indicator === "rsi" ? 50 : 0)} stroke="var(--vui-border-subtle)" strokeDasharray="3 5" />
        {indicator === "macd" ? series.histogram.slice(start, end).map((value, index) => value === null ? null : <rect key={index} x={x(index) - width / 2} y={Math.min(oscY(value), oscY(0))} width={width} height={Math.max(1, Math.abs(oscY(value) - oscY(0)))} fill={value >= 0 ? "var(--state-error)" : "var(--state-success)"} opacity=".6" />) : null}
        {oscillator.slice(0, indicator === "rsi" ? 1 : 2).map((values, index) => <path key={index} d={path(values, oscY)} stroke={index === 0 ? "var(--state-warning)" : "var(--accent-cool)"} strokeWidth="1.5" fill="none" />)}
        <text x={left} y={H - 20} fontSize="11" fill="var(--fg-tertiary)">{indicator === "rsi" ? "RSI(14)" : "MACD(12,26,9)"}</text><text x={W - right + 8} y={305} fontSize="11" fill="var(--fg-tertiary)">{quoteNumber(oscMax)}</text><text x={W - right + 8} y={358} fontSize="11" fill="var(--fg-tertiary)">{quoteNumber(oscMin)}</text>
      </> : null}
      {hover !== null ? <line x1={x(hover)} x2={x(hover)} y1={top} y2={auxiliary ? 360 : 288} stroke="var(--fg-tertiary)" strokeDasharray="3 3" /> : null}
      <text x={left} y={H - 5} fontSize="11" fill="var(--fg-tertiary)">{visible[0].date}</text><text x={W - right} y={H - 5} fontSize="11" textAnchor="end" fill="var(--fg-tertiary)">{visible.at(-1)?.date}</text>
    </svg>
    <p id={readoutId} className={styles.readout} role="status" aria-live="polite">{announcement}</p>
    <div className={styles.footer}><span>{zh ? "成交量" : "Volume"} {quoteNumber(candle?.volumeLots, 0)} {zh ? "手" : "lots"}</span><span>{zh ? "已加载" : "Loaded"} {candles.length} {zh ? "根 · 1 手 = 100 股" : "bars · 1 lot = 100 shares"}</span></div>
  </VSurface>;
}
