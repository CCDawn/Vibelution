import { useEffect, useMemo, useState, type ChangeEvent, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { RefreshCw, Search } from "lucide-react";
import {
  fetchFinancialMarketScreen,
  fetchFinancialStockResearch,
  financialResearchKeys,
  type FinancialMarketScreenFilters,
  type FinancialMarketScreenSort,
  type FinancialMarketScreenStock,
  type FinancialResearchAnnouncement,
  type FinancialResearchNewsItem,
  type FinancialStockResearch,
} from "../../api/financialResearch";
import type { StockIdentity } from "../../api/financialMarket";
import { VButton, VDenseTable, VInput, VSelect, VStateSurface, VSkeleton, VSurface, type VDenseTableColumn } from "../../components/vui";
import {
  EMPTY_FINANCE_SCREEN_PRESET_FILTERS,
  MAX_FINANCE_SCREEN_PRESETS,
  readFinanceScreenPresets,
  writeFinanceScreenPresets,
  type FinanceScreenPreset,
  type FinanceScreenPresetFilters,
} from "./financeScreenPresets";
import styles from "./FinanceMarketExplorer.styles";

type ExplorerMode = "screen" | "news" | "fundamentals";
type ScreenCriteria = Omit<FinancialMarketScreenFilters, "page" | "pageSize">;
const NO_PRESET_ID = "__none__";

const SORT_OPTIONS: Array<{ id: FinancialMarketScreenSort; label: string }> = [
  { id: "changePercent", label: "涨跌幅" },
  { id: "turnoverYuan", label: "成交额" },
  { id: "volumeLots", label: "成交量" },
  { id: "price", label: "股价" },
  { id: "peRatio", label: "市盈率" },
  { id: "pbRatio", label: "市净率" },
];

const DIRECTION_OPTIONS = [
  { id: "desc", label: "从高到低" },
  { id: "asc", label: "从低到高" },
] as const;

function numberFilter(value: string): number | undefined {
  if (!value.trim()) return undefined;
  const result = Number(value);
  return Number.isFinite(result) ? result : undefined;
}

function parseAdvancedFilters(draft: FinanceScreenPresetFilters): { filters?: ScreenCriteria; error?: string } {
  const filters: ScreenCriteria = { sortBy: draft.sortBy, direction: draft.direction };
  const fields: Array<[keyof FinanceScreenPresetFilters, keyof ScreenCriteria, number]> = [
    ["minPrice", "minPrice", 1], ["maxPrice", "maxPrice", 1],
    ["minChangePercent", "minChangePercent", 1], ["maxChangePercent", "maxChangePercent", 1],
    ["minPe", "minPe", 1], ["maxPe", "maxPe", 1],
    ["minPb", "minPb", 1], ["maxPb", "maxPb", 1],
    ["minVolumeLots", "minVolumeLots", 1],
    ["minTurnoverYi", "minTurnoverYuan", 100_000_000],
    ["maxTurnoverYi", "maxTurnoverYuan", 100_000_000],
  ];
  for (const [draftKey, filterKey, multiplier] of fields) {
    const raw = draft[draftKey];
    if (!raw.trim()) continue;
    const value = numberFilter(raw);
    if (value === undefined || !Number.isFinite(value * multiplier)) return { error: "请检查筛选条件中的数字" };
    if (["minPrice", "maxPrice", "minVolumeLots", "minTurnoverYi", "maxTurnoverYi"].includes(draftKey) && value < 0) {
      return { error: "股价、成交量和成交额不能小于 0" };
    }
    if (["minChangePercent", "maxChangePercent"].includes(draftKey) && (value < -100 || value > 10_000)) {
      return { error: "涨跌幅范围应在 -100% 到 10000% 之间" };
    }
    (filters as Record<string, number | string>)[filterKey] = value * multiplier;
  }
  const ranges: Array<[keyof FinanceScreenPresetFilters, keyof FinanceScreenPresetFilters, string]> = [
    ["minPrice", "maxPrice", "股价"], ["minChangePercent", "maxChangePercent", "涨跌幅"],
    ["minPe", "maxPe", "PE"], ["minPb", "maxPb", "PB"],
    ["minTurnoverYi", "maxTurnoverYi", "成交额"],
  ];
  for (const [minimum, maximum, label] of ranges) {
    const minValue = numberFilter(draft[minimum]);
    const maxValue = numberFilter(draft[maximum]);
    if (minValue !== undefined && maxValue !== undefined && minValue > maxValue) return { error: `${label}下限不能大于上限` };
  }
  return { filters };
}

function newPresetId(): string {
  return typeof crypto !== "undefined" && typeof crypto.randomUUID === "function"
    ? crypto.randomUUID()
    : `preset-${Date.now()}-${Math.random().toString(36).slice(2, 10)}`;
}

function quoteNumber(value: number | null | undefined, fractionDigits = 2): string {
  return value === null || value === undefined || !Number.isFinite(value)
    ? "—"
    : value.toLocaleString("zh-CN", { maximumFractionDigits: fractionDigits });
}

function signedPercent(value: number | null): string {
  if (value === null) return "—";
  return `${value > 0 ? "+" : ""}${quoteNumber(value)}%`;
}

function formatTimestamp(value: string | null): string {
  return value?.trim() || "—";
}

function displayMetric(value: number | null, unit: string): string {
  if (value === null || !Number.isFinite(value)) return "—";
  if (unit === "元" && Math.abs(value) >= 100_000_000) {
    return `${quoteNumber(value / 100_000_000)} 亿元`;
  }
  return `${quoteNumber(value)}${unit}`;
}

function marketScreenPrompt(stock: StockIdentity): string {
  return `请研究${stock.name}（${stock.ticker}）。结合可核验的最新行情、公告、新闻和财务指标，说明主要变化、风险与仍缺少的证据；对每个事实标注来源和日期，不要把缺失或日期不明的数据当作最新事实。`;
}

function ScreenTable({
  rows,
  onSelectStock,
  onResearchPrompt,
  researchDisabled,
  zh,
}: {
  rows: FinancialMarketScreenStock[];
  onSelectStock: (stock: StockIdentity) => void;
  onResearchPrompt: (prompt: string) => void;
  researchDisabled: boolean;
  zh: boolean;
}) {
  const columns = useMemo<VDenseTableColumn<FinancialMarketScreenStock>[]>(() => [
    {
      id: "stock", header: zh ? "股票" : "Stock", fill: true, minWidth: 135,
      render: (row) => <VButton variant="ghost" className={styles.stockButton} onPress={() => onSelectStock(row)}>
        <span className={styles.stockCell}><strong className={styles.stockName}>{row.name}</strong><span className={styles.ticker}>{row.ticker} · {row.market}</span></span>
      </VButton>,
    },
    { id: "price", header: zh ? "最新价" : "Price", width: 80, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.price, 3)}</span> },
    {
      id: "change", header: zh ? "涨跌幅" : "Change", width: 88, align: "right",
      render: (row) => <span className={row.changePercent === null ? styles.nullValue : row.changePercent >= 0 ? styles.positive : styles.negative}>{signedPercent(row.changePercent)}</span>,
    },
    { id: "volume", header: zh ? "成交量" : "Volume", width: 92, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.volumeLots, 0)} 手</span> },
    { id: "turnover", header: zh ? "成交额" : "Turnover", width: 106, align: "right", render: (row) => <span className={styles.number}>{row.turnoverYuan === null ? "—" : `${quoteNumber(row.turnoverYuan / 100_000_000)} 亿`}</span> },
    { id: "pe", header: "PE", width: 70, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.peRatio)}</span> },
    { id: "pb", header: "PB", width: 70, align: "right", render: (row) => <span className={styles.number}>{quoteNumber(row.pbRatio)}</span> },
    {
      id: "research", header: zh ? "操作" : "Action", width: 78,
      render: (row) => <VButton
        density="compact"
        variant="ghost"
        isDisabled={researchDisabled}
        disabledReason={researchDisabled ? (zh ? "研究会话忙碌或模型未就绪，请稍后重试。" : "The research session is busy or its model is unavailable. Try again shortly.") : undefined}
        onPress={() => onResearchPrompt(marketScreenPrompt(row))}
      >{zh ? "AI研读" : "Research"}</VButton>,
    },
  ], [onResearchPrompt, onSelectStock, researchDisabled, zh]);

  return <VDenseTable ariaLabel={zh ? "A股行情筛选结果" : "A-share screen results"} columns={columns} rows={rows} getRowKey={(row) => row.symbol} resizable emptyText={zh ? "没有符合条件的股票" : "No matching stocks"} />;
}

function ScreenExplorer({
  agentId,
  onSelectStock,
  onResearchPrompt,
  researchDisabled,
  zh,
}: {
  agentId?: string;
  onSelectStock: (stock: StockIdentity) => void;
  onResearchPrompt: (prompt: string) => void;
  researchDisabled: boolean;
  zh: boolean;
}) {
  const [draft, setDraft] = useState<FinanceScreenPresetFilters>(EMPTY_FINANCE_SCREEN_PRESET_FILTERS);
  const [filters, setFilters] = useState<FinancialMarketScreenFilters>({ page: 1, pageSize: 50, sortBy: "changePercent", direction: "desc" });
  const [presets, setPresets] = useState<FinanceScreenPreset[]>(() => readFinanceScreenPresets(agentId ?? ""));
  const [presetName, setPresetName] = useState("");
  const [selectedPresetId, setSelectedPresetId] = useState(NO_PRESET_ID);
  const [presetMessage, setPresetMessage] = useState("");
  const [presetStorageError, setPresetStorageError] = useState(false);
  const [filterError, setFilterError] = useState("");
  useEffect(() => {
    setPresets(readFinanceScreenPresets(agentId ?? ""));
    setSelectedPresetId(NO_PRESET_ID);
    setPresetMessage("");
    setPresetStorageError(false);
  }, [agentId]);
  const query = useQuery({
    queryKey: financialResearchKeys.screen(filters),
    queryFn: ({ signal }) => fetchFinancialMarketScreen(filters, { signal }),
    staleTime: 5 * 60_000,
    retry: false,
  });

  function updateFilter(name: keyof FinanceScreenPresetFilters) {
    return (event: ChangeEvent<HTMLInputElement>) => setDraft((current) => ({ ...current, [name]: event.target.value }));
  }

  function applyFilters(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const result = parseAdvancedFilters(draft);
    setFilterError(result.error ?? "");
    if (result.filters) setFilters({ ...result.filters, page: 1, pageSize: 50 });
  }

  function clearFilters() {
    setDraft(EMPTY_FINANCE_SCREEN_PRESET_FILTERS);
    setFilterError("");
    setFilters({ page: 1, pageSize: 50, sortBy: "changePercent", direction: "desc" });
  }

  function savePreset() {
    const name = presetName.trim().slice(0, 40);
    if (!name) { setPresetMessage(zh ? "请先填写预设名称" : "Enter a preset name"); return; }
    const parsed = parseAdvancedFilters(draft);
    if (!parsed.filters) { setFilterError(parsed.error ?? ""); return; }
    setFilterError("");
    if (!agentId) { setPresetStorageError(true); return; }
    const existing = presets.find((item) => item.name.toLocaleLowerCase() === name.toLocaleLowerCase());
    if (!existing && presets.length >= MAX_FINANCE_SCREEN_PRESETS) {
      setPresetMessage(zh ? `最多保存 ${MAX_FINANCE_SCREEN_PRESETS} 组，请先删除一组` : `Keep up to ${MAX_FINANCE_SCREEN_PRESETS} presets; delete one first`);
      return;
    }
    const nextPreset: FinanceScreenPreset = { id: existing?.id ?? newPresetId(), name, filters: { ...draft } };
    const next = existing ? presets.map((item) => item.id === existing.id ? nextPreset : item) : [...presets, nextPreset];
    const persisted = writeFinanceScreenPresets(agentId, next);
    setPresetStorageError(!persisted);
    if (persisted) {
      setPresets(next);
      setSelectedPresetId(nextPreset.id);
      setPresetName(name);
      setPresetMessage(zh ? "预设已保存" : "Preset saved");
    }
  }

  function loadPreset() {
    if (selectedPresetId === NO_PRESET_ID) return;
    const preset = presets.find((item) => item.id === selectedPresetId);
    if (!preset) return;
    setDraft({ ...EMPTY_FINANCE_SCREEN_PRESET_FILTERS, ...preset.filters });
    setPresetName(preset.name);
    setPresetMessage(zh ? "已载入条件；点击筛选读取行情" : "Conditions loaded; run the screen to query quotes");
    setFilterError("");
  }

  function deletePreset() {
    if (!agentId || selectedPresetId === NO_PRESET_ID) return;
    const next = presets.filter((item) => item.id !== selectedPresetId);
    const persisted = writeFinanceScreenPresets(agentId, next);
    setPresetStorageError(!persisted);
    if (persisted) {
      setPresets(next);
      setSelectedPresetId(NO_PRESET_ID);
      setPresetName("");
      setPresetMessage(zh ? "预设已删除" : "Preset deleted");
    }
  }

  return <div className={styles.root}>
    <div className={styles.heading}>
      <h2 className={styles.title}>{zh ? "A股行情筛选" : "A-share market screen"}</h2>
      <span className={styles.meta}>{zh ? "新浪 hs_a 行情池 · 延迟数据" : "Sina hs_a universe · Delayed"}</span>
    </div>
    <form className={styles.toolbar} onSubmit={applyFilters}>
      <div className={styles.filters}>
        {([
          ["minPrice", zh ? "最低价" : "Min price"], ["maxPrice", zh ? "最高价" : "Max price"],
          ["minChangePercent", zh ? "最低涨幅 %" : "Min change %"], ["maxChangePercent", zh ? "最高涨幅 %" : "Max change %"],
          ["minPe", zh ? "最低 PE" : "Min PE"], ["maxPe", zh ? "最高 PE" : "Max PE"],
          ["minPb", zh ? "最低 PB" : "Min PB"], ["maxPb", zh ? "最高 PB" : "Max PB"],
          ["minVolumeLots", zh ? "最少成交量（手）" : "Min volume (lots)"],
          ["minTurnoverYi", zh ? "最低成交额（亿元）" : "Min turnover (100m CNY)"],
          ["maxTurnoverYi", zh ? "最高成交额（亿元）" : "Max turnover (100m CNY)"],
        ] as const).map(([key, label]) => {
          const min = key.includes("Change") ? -100 : key.toLowerCase().includes("pe") ? -10_000 : 0;
          const max = key.includes("Change") ? 10_000 : key.toLowerCase().includes("pe") ? 100_000 : undefined;
          return <label className={styles.field} key={key}>{label}<VInput type="number" min={min} max={max} step="any" inputMode="decimal" value={draft[key]} onChange={updateFilter(key)} aria-label={label} className={styles.input} /></label>;
        })}
        <label className={styles.field}>{zh ? "排序" : "Sort by"}<VSelect className={styles.sort} aria-label={zh ? "排序字段" : "Sort field"} selectedKey={draft.sortBy} options={SORT_OPTIONS.map((option) => ({ ...option, label: zh ? option.label : option.id }))} onSelectionChange={(key) => setDraft((current) => ({ ...current, sortBy: String(key) as FinancialMarketScreenSort }))} /></label>
        <label className={styles.field}>{zh ? "顺序" : "Order"}<VSelect className={styles.sort} aria-label={zh ? "排序顺序" : "Sort order"} selectedKey={draft.direction} options={DIRECTION_OPTIONS.map((option) => ({ ...option, label: zh ? option.label : option.id }))} onSelectionChange={(key) => setDraft((current) => ({ ...current, direction: String(key) as FinanceScreenPresetFilters["direction"] }))} /></label>
      </div>
      {agentId ? <div className={styles.presetPanel} aria-label={zh ? "筛选预设" : "Screen presets"}>
        <label className={styles.presetName}>{zh ? "预设名称" : "Preset name"}<VInput value={presetName} maxLength={40} aria-label={zh ? "预设名称" : "Preset name"} placeholder={zh ? "例如：低估值高成交" : "e.g. Value and liquidity"} onChange={(event) => setPresetName(event.target.value)} className={styles.input} /></label>
        <VButton variant="secondary" isDisabled={!presetName.trim() || (presets.length >= MAX_FINANCE_SCREEN_PRESETS && !presets.some((item) => item.name.toLocaleLowerCase() === presetName.trim().toLocaleLowerCase()))} onPress={savePreset}>{zh ? "保存预设" : "Save preset"}</VButton>
        <label className={styles.presetSelect}>{zh ? "已保存" : "Saved"}<VSelect selectedKey={selectedPresetId} aria-label={zh ? "已保存筛选预设" : "Saved screen preset"} options={[{ id: NO_PRESET_ID, label: zh ? "选择预设" : "Choose preset" }, ...presets.map((item) => ({ id: item.id, label: item.name }))]} onSelectionChange={(key) => { if (typeof key === "string") setSelectedPresetId(key); }} /></label>
        <VButton variant="ghost" isDisabled={selectedPresetId === NO_PRESET_ID} onPress={loadPreset}>{zh ? "载入" : "Load"}</VButton>
        <VButton variant="ghost" isDisabled={selectedPresetId === NO_PRESET_ID} onPress={deletePreset}>{zh ? "删除" : "Delete"}</VButton>
        <span className={styles.presetCount}>{presets.length}/{MAX_FINANCE_SCREEN_PRESETS}</span>
      </div> : null}
      {presetStorageError ? <p className={styles.warning} role="alert">{zh ? "筛选预设无法保存在此浏览器" : "Presets could not be saved in this browser"}</p> : null}
      {presetMessage ? <p className={styles.presetMessage} role="status">{presetMessage}</p> : null}
      {filterError ? <p className={styles.warning} role="alert">{filterError}</p> : null}
      <div className={styles.actions}>
        <div className={styles.actionGroup}>
          <VButton type="button" variant="ghost" onPress={clearFilters}>{zh ? "清除" : "Clear"}</VButton>
          <VButton type="submit" variant="primary" icon={<Search size={14} />} isPending={query.isFetching}>{zh ? "筛选" : "Screen"}</VButton>
          <VButton type="button" variant="secondary" icon={<RefreshCw size={14} />} isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新" : "Refresh"}</VButton>
        </div>
      </div>
    </form>

    {query.isPending ? <VStateSurface tone="loading" busy title={zh ? "正在加载A股行情" : "Loading A-share quotes"}>{zh ? "首次读取需要拉取行情覆盖数据。" : "The first load reads the available quote universe."}</VStateSurface>
      : query.isError && !query.data ? <VStateSurface tone="error" title={zh ? "行情筛选失败" : "Market screen unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>
        : query.data ? <>
          {query.error ? <VStateSurface tone="error" density="compact" title={zh ? "刷新失败，当前显示上次成功获取的数据" : "Refresh failed; showing the last successfully fetched data"} actions={<VButton isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface> : null}
          <div className={styles.coverage} aria-live="polite">
            <div className={styles.coverageFacts}>
              <span className={styles.coverageFact}>{zh ? "新浪 hs_a 行情池" : "Sina hs_a universe"} {query.data.coverage.loaded.toLocaleString()} / {query.data.coverage.providerTotal.toLocaleString()}</span>
              <span className={styles.coverageFact}>{zh ? "符合条件" : "Matches"} {query.data.coverage.totalFiltered.toLocaleString()}</span>
              <span className={styles.coverageFact}>{zh ? "行情时点" : "Quote time"} {query.data.dataTime ?? "—"} · {query.data.dataDate?.trim() || (zh ? "日期未提供" : "Date unavailable")}</span>
              <span className={styles.coverageFact}>{zh ? "来源" : "Source"} {query.data.source} · {zh ? "上次成功抓取" : "Last successful fetch"} {formatTimestamp(query.data.fetchedAt)}</span>
            </div>
            <p className={styles.meta}>{zh ? "完整读取仅代表新浪 hs_a 行情池，不等于全市场覆盖。" : "Complete means the Sina hs_a universe was loaded; it does not cover the entire market."}</p>
            {!query.data.coverage.complete ? <VStateSurface tone="unavailable" density="compact" title={zh ? "筛选结果只含已加载项" : "Results include loaded items only"}>
              {zh ? `部分结果仅基于已加载项：${query.data.coverage.loaded.toLocaleString()} / ${query.data.coverage.providerTotal.toLocaleString()} 只。` : `Partial results include loaded items only: ${query.data.coverage.loaded.toLocaleString()} of ${query.data.coverage.providerTotal.toLocaleString()} stocks.`}
              {query.data.coverage.failedPages.length ? ` ${zh ? "失败页" : "Failed pages"}: ${query.data.coverage.failedPages.join(", ")}` : ""}
            </VStateSurface> : null}
          </div>
          <div className={styles.tableWrap}><ScreenTable rows={query.data.items} onSelectStock={onSelectStock} onResearchPrompt={onResearchPrompt} researchDisabled={researchDisabled} zh={zh} /></div>
          <div className={styles.source}>
            <a href={query.data.sourceUrl} target="_blank" rel="noreferrer" className={styles.itemLink}>{zh ? "行情来源" : "Quote source"}</a>
            <div className={styles.paging}>
              <VButton variant="ghost" isDisabled={query.data.page <= 1 || query.isFetching} onPress={() => setFilters((current) => ({ ...current, page: Math.max(1, (current.page ?? 1) - 1) }))}>{zh ? "上一页" : "Previous"}</VButton>
              <span>{query.data.page} / {Math.max(1, Math.ceil(query.data.coverage.totalFiltered / query.data.pageSize))}</span>
              <VButton variant="ghost" isDisabled={query.data.page * query.data.pageSize >= query.data.coverage.totalFiltered || query.isFetching} onPress={() => setFilters((current) => ({ ...current, page: (current.page ?? 1) + 1 }))}>{zh ? "下一页" : "Next"}</VButton>
            </div>
          </div>
        </> : null}
  </div>;
}

function FacetMeta({ data, zh }: { data: { source: string; sourceUrl: string; fetchedAt: string }; zh: boolean }) {
  return <div className={styles.itemMeta}><span>{data.source}</span><span>{zh ? "上次成功抓取" : "Last successful fetch"} {formatTimestamp(data.fetchedAt)}</span><a className={styles.itemLink} href={data.sourceUrl} target="_blank" rel="noreferrer">{zh ? "来源" : "Source"}</a></div>;
}

function ResearchList<T extends FinancialResearchNewsItem | FinancialResearchAnnouncement>({
  title,
  items,
  facet,
  zh,
}: {
  title: string;
  items: T[];
  facet: FinancialStockResearch["news"] | FinancialStockResearch["announcements"];
  zh: boolean;
}) {
  return <section className={styles.section}>
    <div className={styles.sectionHeader}><h3 className={styles.sectionTitle}>{title}</h3><FacetMeta data={facet} zh={zh} /></div>
    {facet.status === "available" && facet.error ? <VStateSurface tone="unavailable" density="compact" title={zh ? "来源限制" : "Source limitations"}>{facet.error}</VStateSurface> : null}
    {facet.status === "unavailable" ? <VStateSurface tone="error" density="compact" title={zh ? "此数据源暂不可用" : "Source unavailable"}>{facet.error}</VStateSurface>
      : items.length ? <ul className={styles.list}>{items.map((item, index) => <li className={styles.listItem} key={`${item.url ?? item.title}:${index}`}>
        {item.url ? <a className={styles.itemTitleLink} href={item.url} target="_blank" rel="noreferrer">{item.title}</a> : <strong className={styles.itemTitle}>{item.title}</strong>}
        <div className={styles.itemMeta}><span>{"publisher" in item && item.publisher ? item.publisher : zh ? "公司公告" : "Filing"}</span><time dateTime={item.publishedAt ?? undefined}>{item.publishedAt ?? (zh ? "时间未提供" : "Date unavailable")}</time></div>
      </li>)}</ul> : <p className={styles.meta}>{zh ? "暂无相关内容" : "No related items"}</p>}
  </section>;
}

function StockResearch({ stock, mode, onResearchPrompt, zh }: { stock: StockIdentity; mode: Exclude<ExplorerMode, "screen">; onResearchPrompt: (prompt: string) => void; zh: boolean }) {
  const query = useQuery({
    queryKey: financialResearchKeys.stock(stock.symbol),
    queryFn: ({ signal }) => fetchFinancialStockResearch(stock.symbol, { signal }),
    staleTime: 3 * 60_000,
    retry: false,
  });
  if (query.isPending) return <VStateSurface tone="loading" busy title={zh ? `正在查找${stock.name}资料` : `Loading ${stock.name} research`}><VSkeleton /></VStateSurface>;
  if (query.isError && !query.data) return <VStateSurface tone="error" title={zh ? "股票资料加载失败" : "Stock research unavailable"} actions={<VButton onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface>;
  if (!query.data) return null;

  const report = query.data.fundamentals;
  const prompt = marketScreenPrompt(stock);
  return <div className={styles.root}>
    {query.error ? <VStateSurface tone="error" density="compact" title={zh ? "刷新失败，当前显示上次成功获取的数据" : "Refresh failed; showing the last successfully fetched data"} actions={<VButton isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "重试" : "Retry"}</VButton>}>{query.error.message}</VStateSurface> : null}
    <div className={styles.heading}>
      <div><h2 className={styles.title}>{stock.name} <span className={styles.ticker}>{stock.ticker} · {stock.market}</span></h2><p className={styles.meta}>{zh ? "公开资料 · 以来源披露时间为准" : "Public data · use provider publication dates"}</p></div>
      <div className={styles.actions}>
        <VButton variant="secondary" icon={<RefreshCw size={14} />} isDisabled={query.isFetching} onPress={() => void query.refetch()}>{zh ? "刷新资料" : "Refresh sources"}</VButton>
        <VButton variant="primary" onPress={() => onResearchPrompt(prompt)}>{zh ? "AI交叉研判" : "Ask AI to review"}</VButton>
      </div>
    </div>
    {mode === "news" ? <>
      <ResearchList title={zh ? "相关新闻" : "News"} items={query.data.news.items} facet={query.data.news} zh={zh} />
      <ResearchList title={zh ? "公司公告" : "Filings"} items={query.data.announcements.items} facet={query.data.announcements} zh={zh} />
    </> : <section className={styles.section}>
      <div className={styles.sectionHeader}><h3 className={styles.sectionTitle}>{zh ? "财务指标" : "Fundamentals"}</h3><FacetMeta data={report} zh={zh} /></div>
      {report.status === "unavailable" ? <VStateSurface tone="error" density="compact" title={zh ? "财务数据源暂不可用" : "Fundamentals unavailable"}>{report.error}</VStateSurface>
        : <>
          {report.error ? <VStateSurface tone="unavailable" density="compact" title={zh ? "来源限制" : "Source limitations"}>{report.error}</VStateSurface> : null}
          <div className={styles.metrics}>{report.items.map((item) => <VSurface key={item.key} tone="row" className={styles.metric}>
            <span className={styles.metricLabel}>{item.label}</span>
            <strong className={styles.metricValue}>{displayMetric(item.value, item.unit)}</strong>
            <span className={styles.metricMeta}>{zh ? "报告期" : "Period"} {item.reportDate ?? report.reportDate ?? "—"}{item.publishedAt || report.publishedAt ? ` · ${zh ? "披露" : "Filed"} ${item.publishedAt ?? report.publishedAt}` : ""}</span>
          </VSurface>)}</div>
          <p className={styles.meta}>{zh ? "缺失指标显示为 —；财务期末日与公告披露日分别列示。" : "Missing values appear as —; period-end and filing dates are shown separately."}</p>
        </>}
    </section>}
  </div>;
}

export function FinanceMarketExplorer({
  agentId,
  mode,
  stock,
  onSelectStock,
  onResearchPrompt,
  researchDisabled = false,
  zh,
}: {
  agentId?: string;
  mode: ExplorerMode;
  stock: StockIdentity;
  onSelectStock: (stock: StockIdentity) => void;
  onResearchPrompt: (prompt: string) => void;
  researchDisabled?: boolean;
  zh: boolean;
}) {
  return mode === "screen"
    ? <ScreenExplorer agentId={agentId} onSelectStock={onSelectStock} onResearchPrompt={onResearchPrompt} researchDisabled={researchDisabled} zh={zh} />
    : <StockResearch stock={stock} mode={mode} onResearchPrompt={onResearchPrompt} zh={zh} />;
}
