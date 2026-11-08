import { lazy, Suspense, type ComponentType, type ReactNode } from "react";
import { VSkeleton } from "../../components/vui";

/**
 * Lazy registry for secondary finance areas. Every panel here renders only on
 * an explicit area/tab navigation (dashboard, screen, team, account, backtest,
 * review, portfolio, memory/skills/learning, tasks, reports, watchlist,
 * evidence aside, news/fundamentals tabs), never on the default research
 * workspace first paint. Splitting them keeps the FinanceRoute chunk on its
 * cold-navigation budget; each panel chunk stays far under the generic
 * per-chunk budget.
 */

/**
 * React.lazy wrapper that keeps the picked component's exact prop types: the
 * module promise's named export becomes the lazy default.
 */
function lazyNamed<M extends object, K extends keyof M>(module: Promise<M>, pick: K): M[K] {
  return lazy(async () => {
    const loaded = await module;
    return { default: loaded[pick] as ComponentType<any> };
  }) as unknown as M[K];
}

/** Suspense surface for lazy finance panels; the skeleton keeps pane geometry. */
export function FinanceLazySurface({ children, className }: { children?: ReactNode; className?: string }) {
  return <Suspense fallback={<VSkeleton className={className} />}>{children}</Suspense>;
}

export const FinanceDashboard = lazyNamed(import("./FinanceDashboard"), "FinanceDashboard");
export const FinanceGeneralResearch = lazyNamed(import("./FinanceGeneralResearch"), "FinanceGeneralResearch");
export const FinanceKnowledgeCenter = lazyNamed(import("./FinanceKnowledgeCenter"), "FinanceKnowledgeCenter");
export const FinanceLessonManager = lazyNamed(import("./FinanceLessonManager"), "FinanceLessonManager");
export const FinanceTaskCenter = lazyNamed(import("./FinanceTaskCenter"), "FinanceTaskCenter");
export const FinanceMarketExplorer = lazyNamed(import("./FinanceMarketExplorer"), "FinanceMarketExplorer");
export const FinanceWatchlistTable = lazyNamed(import("./FinanceWatchlistTable"), "FinanceWatchlistTable");
export const FinanceBacktest = lazyNamed(import("./FinanceBacktest"), "FinanceBacktest");
export const FinanceOutcomeReview = lazyNamed(import("./FinanceOutcomeReview"), "FinanceOutcomeReview");
export const FinancePaperTrading = lazyNamed(import("./FinancePaperTrading"), "FinancePaperTrading");
export const FinanceAnalystTeam = lazyNamed(import("./FinanceAnalystTeam"), "FinanceAnalystTeam");
export const FinanceAnalystTeamInspector = lazyNamed(import("./FinanceAnalystTeam"), "FinanceAnalystTeamInspector");
export const FinancePortfolioResearch = lazyNamed(import("./FinancePortfolioResearch"), "FinancePortfolioResearch");
export const FinanceReportLibrary = lazyNamed(import("./FinanceReportLibrary"), "FinanceReportLibrary");
export const FinanceReportsCenter = lazyNamed(import("./FinanceReportsCenter"), "FinanceReportsCenter");
export const FinanceResearchHistory = lazyNamed(import("./FinanceResearchHistory"), "FinanceResearchHistory");
export const FinanceManualPositions = lazyNamed(import("./FinanceManualPositions"), "FinanceManualPositions");
export const FinanceScreenWorkspace = lazyNamed(import("./FinanceScreenWorkspace"), "FinanceScreenWorkspace");
