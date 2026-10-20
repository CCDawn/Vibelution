import { useRef, useState, type FormEvent } from "react";
import type { FinancialManualPosition } from "../../api/types/financialPreferences";
import { VButton, VCheckbox, VInput, VStateSurface } from "../../components/vui";
import styles from "./FinanceAdvisorExecution.styles";

const MAX_POSITION_ROWS = 50;
const A_SHARE_SYMBOL = /^(?:sh(?:60|68)\d{4}|sz(?:00|30)\d{4}|bj\d{6})$/;

type PositionDraft = {
  id: string;
  symbol: string;
  originalSymbol: string;
  stock: FinancialManualPosition["stock"];
  quantity: string;
  costPrice: string;
  note: string;
  fromBaseline: boolean;
};

function draftFromPosition(position: FinancialManualPosition): PositionDraft {
  return {
    id: position.id,
    symbol: position.stock.symbol,
    originalSymbol: position.stock.symbol,
    stock: { ...position.stock },
    quantity: String(position.quantity),
    costPrice: String(position.costPrice),
    note: position.note,
    fromBaseline: true,
  };
}

function newPositionDraft(): PositionDraft {
  const id = globalThis.crypto?.randomUUID?.() ?? `manual-${Date.now()}-${Math.random().toString(36).slice(2)}`;
  return {
    id,
    symbol: "",
    originalSymbol: "",
    stock: { symbol: "", ticker: "", name: "", market: "" },
    quantity: "",
    costPrice: "",
    note: "",
    fromBaseline: false,
  };
}

function marketName(symbol: string) {
  if (symbol.startsWith("sh")) return "上交所";
  if (symbol.startsWith("sz")) return "深交所";
  return "北交所";
}

function submissionError(cashValue: string, positions: PositionDraft[], confirmed: boolean, zh: boolean) {
  if (!confirmed) return zh ? "请先确认这是一份完整的实际账户快照。" : "Confirm that this is a complete snapshot of the actual account.";
  if (!cashValue.trim()) return zh ? "请输入当前实际可用现金；0 也可以。" : "Enter current available cash; 0 is allowed.";
  const cash = Number(cashValue);
  if (!Number.isFinite(cash) || cash < 0) return zh ? "可用现金必须是大于或等于 0 的有效数字。" : "Available cash must be a finite number at least 0.";
  if (positions.length > MAX_POSITION_ROWS) return zh ? `持仓最多支持 ${MAX_POSITION_ROWS} 条，请先移除多余行。` : `A maximum of ${MAX_POSITION_ROWS} holdings is supported. Remove extra rows first.`;

  const seen = new Set<string>();
  for (let index = 0; index < positions.length; index += 1) {
    const position = positions[index];
    const symbol = position.symbol.trim();
    const row = index + 1;
    if (!A_SHARE_SYMBOL.test(symbol)) {
      return zh
        ? `第 ${row} 条股票代码无效。请输入 sh60/68、sz00/30 或 bj 开头的 6 位 A 股代码。`
        : `Holding ${row} has an invalid code. Use a six-digit A-share code prefixed by sh60/68, sz00/30, or bj.`;
    }
    if (seen.has(symbol)) return zh ? `股票代码 ${symbol} 重复，请合并或移除重复持仓。` : `Holding ${symbol} is duplicated. Merge or remove the duplicate.`;
    seen.add(symbol);
    const quantity = Number(position.quantity);
    if (!position.quantity.trim() || !Number.isFinite(quantity) || !Number.isInteger(quantity) || quantity <= 0) {
      return zh ? `第 ${row} 条持仓数量必须是大于 0 的整数。` : `Holding ${row} quantity must be a positive integer.`;
    }
    const costPrice = Number(position.costPrice);
    if (!position.costPrice.trim() || !Number.isFinite(costPrice) || costPrice <= 0) {
      return zh ? `第 ${row} 条持仓成本必须是大于 0 的有效数字。` : `Holding ${row} cost must be a finite number greater than 0.`;
    }
  }
  return "";
}

function actualPosition(position: PositionDraft): FinancialManualPosition {
  const symbol = position.symbol.trim();
  const stock = symbol === position.originalSymbol
    ? {
      symbol,
      ticker: position.stock.ticker,
      name: position.stock.name,
      market: position.stock.market,
    }
    : {
      symbol,
      ticker: symbol.slice(2),
      name: symbol.slice(2),
      market: marketName(symbol),
    };
  return {
    id: position.id,
    stock,
    quantity: Number(position.quantity),
    costPrice: Number(position.costPrice),
    currency: "CNY",
    note: symbol === position.originalSymbol ? position.note : "",
  };
}

/** Mount this form for a fresh review; registered positions are only editable baselines. */
export function FinanceAdvisorExecution({ initialPositions, initialCash, pending, zh, onConfirm }: {
  initialPositions: FinancialManualPosition[];
  initialCash: number | null;
  pending: boolean;
  zh: boolean;
  onConfirm: (actualCashCny: number, actualPositions: FinancialManualPosition[]) => Promise<void>;
}) {
  const [cash, setCash] = useState("");
  const [positions, setPositions] = useState(() => initialPositions.map(draftFromPosition));
  const [confirmed, setConfirmed] = useState(false);
  const [error, setError] = useState("");
  const [saved, setSaved] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const gate = useRef(false);
  const isPending = pending || submitting;
  const cashLabel = zh ? "实际可用现金（元）" : "Actual available cash (CNY)";

  function changed() {
    setConfirmed(false);
    setError("");
    setSaved(false);
  }

  function updatePosition(index: number, update: (position: PositionDraft) => PositionDraft) {
    changed();
    setPositions(current => current.map((position, currentIndex) => currentIndex === index ? update(position) : position));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (gate.current || isPending) return;
    const problem = submissionError(cash, positions, confirmed, zh);
    if (problem) {
      setError(problem);
      setSaved(false);
      return;
    }

    gate.current = true;
    setSubmitting(true);
    setError("");
    setSaved(false);
    try {
      await onConfirm(Number(cash), positions.map(actualPosition));
      setSaved(true);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : String(cause));
    } finally {
      gate.current = false;
      setSubmitting(false);
    }
  }

  return <form className={styles.root} noValidate onSubmit={event => void submit(event)}>
    <p className={styles.notice}>{zh
      ? "已有记录只作核对基线，不代表当前账户。请填写实际可用现金，逐项核对、修改或删除登记持仓，并补齐全部实际持仓。"
      : "Existing records are review baselines only and do not represent the current account. Enter actual available cash, review, edit or remove each registered holding, and add every actual holding."}</p>
    <p className={styles.baseline}>{zh ? "现有现金基线（仅供参考）" : "Registered cash baseline (reference only)"}: {initialCash === null
      ? (zh ? "未记录" : "Not recorded")
      : `${initialCash.toLocaleString(zh ? "zh-CN" : "en-US")} ${zh ? "元" : "CNY"}`}</p>

    <label className={styles.field}>{cashLabel}
      <VInput aria-label={cashLabel} type="number" min="0" step="any" value={cash} placeholder={zh ? "请输入当前实际可用现金" : "Enter current available cash"} disabled={isPending} onChange={event => { setCash(event.target.value); changed(); }} />
    </label>

    <section className={styles.holdings} aria-label={zh ? "实际持仓" : "Actual holdings"}>
      <div className={styles.sectionHeading}>
        <h3>{zh ? "完整实际持仓" : "Complete actual holdings"}</h3>
        <p>{zh ? "代码仅支持 sh60/68、sz00/30、bj 开头的 A 股。" : "A-share codes only: sh60/68, sz00/30, or bj prefixes."}</p>
      </div>
      {positions.length === 0
        ? <p className={styles.empty}>{zh ? "当前没有持仓行。若账户确实没有持仓，请在下方明确确认空列表。" : "There are no holding rows. If the account has no holdings, explicitly confirm the empty list below."}</p>
        : <div className={styles.positionList}>
          {positions.map((position, index) => {
            const symbolLabel = zh ? `持仓 ${index + 1} 股票代码` : `Holding ${index + 1} stock code`;
            const quantityLabel = zh ? `持仓 ${index + 1} 持有数量（股）` : `Holding ${index + 1} quantity (shares)`;
            const costLabel = zh ? `持仓 ${index + 1} 持仓成本（元/股）` : `Holding ${index + 1} cost (CNY/share)`;
            const currentSymbol = position.symbol.trim();
            const displayName = currentSymbol === position.originalSymbol
              ? position.stock.name
              : currentSymbol ? currentSymbol.slice(2) : (zh ? "未填写" : "Not entered");
            return <fieldset className={styles.position} key={position.id}>
              <legend className={styles.positionLegend}>{position.fromBaseline
                ? (zh ? `登记基线 ${index + 1}，请核对` : `Registered baseline ${index + 1}; review it`)
                : (zh ? `新增实际持仓 ${index + 1}` : `New actual holding ${index + 1}`)}</legend>
              <div className={styles.positionFields}>
                <p className={styles.positionIdentity}>{zh ? "名称" : "Name"}: {displayName || (zh ? "未记录" : "Not recorded")}</p>
                <label className={styles.field}>{symbolLabel}
                  <VInput aria-label={symbolLabel} autoCapitalize="none" autoComplete="off" spellCheck={false} value={position.symbol} placeholder={zh ? "例如 sh600000" : "For example, sh600000"} disabled={isPending} onChange={event => updatePosition(index, current => ({ ...current, symbol: event.target.value }))} />
                </label>
                <label className={styles.field}>{quantityLabel}
                  <VInput aria-label={quantityLabel} type="number" min="1" step="1" value={position.quantity} placeholder={zh ? "正整数" : "Positive integer"} disabled={isPending} onChange={event => updatePosition(index, current => ({ ...current, quantity: event.target.value }))} />
                </label>
                <label className={styles.field}>{costLabel}
                  <VInput aria-label={costLabel} type="number" min="0" step="any" value={position.costPrice} placeholder={zh ? "大于 0" : "Greater than 0"} disabled={isPending} onChange={event => updatePosition(index, current => ({ ...current, costPrice: event.target.value }))} />
                </label>
                <VButton type="button" variant="ghost" isDisabled={isPending} onPress={() => {
                  changed();
                  setPositions(current => current.filter((_, currentIndex) => currentIndex !== index));
                }}>{zh ? "移除" : "Remove"}</VButton>
              </div>
            </fieldset>;
          })}
        </div>}
      <div className={styles.actions}>
        <VButton type="button" variant="ghost" isDisabled={isPending || positions.length >= MAX_POSITION_ROWS} onPress={() => {
          changed();
          setPositions(current => current.length >= MAX_POSITION_ROWS ? current : [...current, newPositionDraft()]);
        }}>{zh ? "添加持仓" : "Add holding"}</VButton>
        <span className={styles.rowCount}>{zh ? `${positions.length}/${MAX_POSITION_ROWS} 条` : `${positions.length}/${MAX_POSITION_ROWS} holdings`}</span>
      </div>
    </section>

    <VCheckbox isSelected={confirmed} isDisabled={isPending} onChange={value => {
      setConfirmed(value === true);
      setError("");
      setSaved(false);
    }}>{positions.length === 0
      ? (zh ? "我确认当前没有任何持仓，并确认空列表就是完整的实际持仓快照。" : "I confirm there are no holdings and this empty list is the complete actual snapshot.")
      : (zh ? "我已核对并确认这份清单包含当前全部实际持仓。" : "I reviewed this list and confirm it contains every actual holding." )}</VCheckbox>

    {error ? <VStateSurface role="alert" tone="error" density="compact" title={error} /> : null}
    {saved ? <p className={styles.success} role="status">{zh ? "实际账户快照已确认并提交。" : "The actual account snapshot was confirmed and submitted."}</p> : null}
    <VButton type="submit" isDisabled={isPending || saved}>{isPending
      ? (zh ? "正在提交…" : "Submitting…")
      : (zh ? "确认实际账户快照" : "Confirm actual account snapshot")}</VButton>
  </form>;
}

export default FinanceAdvisorExecution;
