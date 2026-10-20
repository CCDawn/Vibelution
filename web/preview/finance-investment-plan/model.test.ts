import { describe, expect, it } from "vitest";
import { calculate, demonstration, errorsFor, initial } from "./model";

describe("investment preview constraints (fixtures only)", () => {
  it("does not invent the missing user risk and account conditions", () => {
    expect(initial.loss).toBe("");
    expect(Object.keys(errorsFor(initial))).toEqual(expect.arrayContaining(["reserve", "loss", "concentration", "goal", "permission", "holdings"]));
    expect(errorsFor(demonstration)).toEqual({});
  });
  it("accounts for minimum commission before selecting a 100-share lot", () => {
    const p = calculate({ ...demonstration, budget: "3600", reserve: "0", concentration: "50" });
    expect(p.rows[0].shares).toBe(0); // 1800 cannot cover a 1800 lot plus fees.
    expect(p.cost + p.cash).toBe(360000);
  });
  it("respects cash reserve and concentration across small budgets", () => {
    for (const budget of [1000, 3000, 6000, 8000, 10000, 100000]) {
      for (const percentage of [5, 20, 40, 100]) {
        const c = { ...demonstration, budget: String(budget), reserve: String(budget / 3), concentration: String(percentage) };
        const p = calculate(c);
        expect(p.cash).toBeGreaterThanOrEqual(Math.round(budget / 3 * 100));
        expect(p.cost + p.cash).toBe(budget * 100);
        p.rows.forEach(row => {
          expect(row.shares % 100).toBe(0);
          expect(row.weight).toBeLessThanOrEqual(percentage);
          expect(row.cost).toBe(row.gross + row.fees);
        });
      }
    }
  });
  it("keeps cash when no loss is accepted or no lot is affordable", () => {
    expect(calculate({ ...demonstration, loss: "0" }).cost).toBe(0);
    expect(calculate({ ...demonstration, budget: "1000", reserve: "0" }).cost).toBe(0);
  });
  it("rejects invalid budget, inconsistent amounts and unentered holdings", () => {
    expect(errorsFor({ ...demonstration, budget: "-1" })).toHaveProperty("budget");
    expect(errorsFor({ ...demonstration, reserve: "6000.01" })).toHaveProperty("reserve");
    expect(errorsFor({ ...demonstration, loss: "NaN" })).toHaveProperty("loss");
    expect(errorsFor({ ...demonstration, concentration: "101" })).toHaveProperty("concentration");
    expect(errorsFor({ ...demonstration, holdings: "yes" })).toHaveProperty("holdings");
  });
});
