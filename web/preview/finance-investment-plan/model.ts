/** Deterministic UI fixtures only. No market feeds, personal persistence or trading. */
export type Conditions = {
  budget: string; reserve: string; loss: string; concentration: string;
  horizon: string; flexible: string; goal: string; permission: string; holdings: string;
};
export const initial: Conditions = {
  budget: "6000", reserve: "", loss: "", concentration: "",
  horizon: "6", flexible: "yes", goal: "", permission: "", holdings: "",
};
export const demonstration: Conditions = {
  ...initial, reserve: "2000", loss: "1200", concentration: "40",
  goal: "平衡增长", permission: "main", holdings: "none",
};
export function errorsFor(c: Conditions): Record<string, string> {
  const errors: Record<string, string> = {};
  const numeric = (key: keyof Conditions, min: number, max: number, label: string) => {
    const value = c[key].trim();
    if (!value || !Number.isFinite(Number(value)) || Number(value) < min || Number(value) > max || !/^\d+(\.\d{1,2})?$/.test(value))
      errors[key] = `${label}需为 ${min}–${max} 之间的有效金额或数值`;
  };
  numeric("budget", 1, 100000000, "预算");
  numeric("reserve", 0, Number(c.budget) || 0, "保留现金");
  numeric("loss", 0, Number(c.budget) || 0, "可接受亏损");
  numeric("concentration", 1, 100, "单只股票占比");
  if (!c.goal) errors.goal = "请先选择投资目标";
  if (!c.permission) errors.permission = "请确认可交易的范围";
  if (c.holdings !== "none") errors.holdings = c.holdings === "yes" ? "本预览尚未录入已有持仓，先展示条件检查" : "请确认是否已有持仓";
  return errors;
}
const stocks = [
  { name: "示例银行 A", price: 18, reason: "演示分红、盈利质量与估值的比较方式。", risk: "重点核对资产质量、息差和分红可持续性。" },
  { name: "示例公用事业 B", price: 12.5, reason: "演示不同行业之间的资金分配方式。", risk: "重点核对现金流、资本开支与负债成本。" },
];
export function calculate(c: Conditions) {
  const budget = Math.round(Number(c.budget) * 100);
  const reserve = Math.round(Number(c.reserve) * 100);
  const allowance = Number(c.loss) === 0 ? 0 : Math.floor(Math.min((budget - reserve) / stocks.length, budget * Number(c.concentration) / 100));
  const rows = stocks.map(stock => {
    const price = Math.round(stock.price * 100);
    let shares = Math.floor(allowance / (price * 100)) * 100;
    const feeFor = (n: number) => n ? Math.max(500, Math.round(price * n * 0.0003)) + Math.round(price * n * 0.00001) : 0;
    while (shares > 0 && price * shares + feeFor(shares) > allowance) shares -= 100;
    const gross = shares * price, fees = feeFor(shares);
    return { ...stock, shares, gross, fees, cost: gross + fees, weight: budget > 0 ? gross / budget * 100 : 0 };
  });
  const cost = rows.reduce((sum, row) => sum + row.cost, 0);
  const gross = rows.reduce((sum, row) => sum + row.gross, 0);
  return { rows, cost, gross, cash: budget - cost, budget, fees: cost - gross };
}
export const money = (cents: number) => `¥${(cents / 100).toLocaleString("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
