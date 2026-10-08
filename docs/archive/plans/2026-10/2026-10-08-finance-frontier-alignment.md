# Finance research and simulation alignment

Status: active implementation. This is a task plan, not a product specification or proof of parity.

## Outcome and boundaries

Close the capability gaps reviewed on 2026-10-08 against TradingAgents, TradingAgents-CN and AI Hedge Fund. Preserve the approved desktop conversation-first three-column VUI workspace, native Session/Turn authority, private Agent ownership and user-approved simulation. Broker orders, new paid-data subscriptions, remote publishing and profitability claims are outside this work.

The baseline already supports analyst collaboration, cited reports, market research, a private paper ledger and single-stock daily AI backtests. Each new capability must use a real end-to-end path, preserve unavailable data explicitly and pass domain/API tests plus isolated runtime acceptance where applicable.

## Ordered delivery

1. **Research-linked portfolio execution.** Reuse completed canonical report exports and the existing private paper ledger. Generate explicit target weights, show deterministic risk checks and estimated orders, then require explicit approval of the exact plan before an atomic, idempotent simulated batch. Account changes, stale quotes, ownership changes or altered plans invalidate execution. Persist proposal and execution references for review. No automatic execution on reads, model response or page reload.
2. **Portfolio backtesting.** Reuse immutable daily datasets and accounting rules. Add a shared-cash multi-symbol portfolio, allocation/rebalance cadence and comparable benchmark. Preserve no-future inputs, next-open execution, costs and missing-coverage rejection. Keep legacy single-stock endpoints compatible.
3. **Historical research evidence.** Add timestamped publication-aware fundamentals/disclosures and explicit historical-news coverage. Historical inputs must be available by the decision timestamp. Missing historical sources are unavailable, never substituted with present-day text.
4. **Evaluation.** Compare strategies/models on a fixed symbol/date grid with held-out periods, per-window coverage, cost and risk/return summaries. Record dataset/model/strategy hashes. Operational success and strategy quality are separate results; superiority is never assumed.
5. **Continuous paper workflow and acceptance.** Reuse managed tasks and the established ledger for repeatable research/proposal/review, bounded scheduling and a stop control. Approvals bind to the exact proposed orders. Verify recovery, history, export and desktop 1280/1920 layouts before integration.

## First delivery contract

Additive portfolio endpoints and finance-scoped artifacts only; do not change ordinary Session admission, Journal, worker or SSE. The paper ledger remains the only writer of simulated cash, positions and fills. Preview/model inference cannot write orders. Execution validates account fingerprint and proposal hash under the same ledger lock, applies sells before buys to a copied ledger, and persists all fills once or none. Duplicate accepted requests return the original result.

Default risk policy is explicit and editable: long-only A-share cash account, maximum single-position allocation, minimum cash reserve, turnover limit, bounded quote age and no leverage. A failed rule must explain its measured value and limit. An LLM cannot override these rules. Research text is untrusted data, and all source Session/Turn ownership is checked server-side.

## Verification and progress

- Baseline: AI single-stock backtest merged and isolated runtime accepted; this does not prove portfolio or full research parity.
- First delivery: validated and integrated locally on 2026-10-09; isolated runtime stopped and task checkout archived. Accounting conservation, failed-batch rollback, stale-account rejection, approval replay, ownership isolation, T+1 and bounded market data have targeted regression coverage. Shared-runtime refresh remains separate.
- Isolated runtime acceptance on 2026-10-08: an owned native research Turn generated a real two-bank report and model allocation. A manually increased single-stock target was blocked, restoring the permitted target passed, and explicit approval created two simulated fills. The account retained cash 704320.32 and charged fees 88.68 from initial cash 1000000.00; replaying approval did not change cash or the two orders. Page reload and official Launcher restart preserved the holdings, proposal history and trade-review totals. Exact Session/Turn JSON source export was verified.
- Runtime-discovered repairs: guidance no longer hides the original research report; pending creation no longer reads a nonexistent proposal; long source previews use one line with expansion; executed history does not request an impossible expiry recheck. The model now receives deterministic account values. Detected numeric sentences in model explanations are omitted with a notice, without altering structured targets or orders. A final real-model call produced a ready two-stock plan with qualitative rationale, an omission notice and correct account/fee figures.
- Browser acceptance: 1280x900 and 1920x1080 desktop layouts retain all three panes without document overflow. Report previews remain one line with expansion. Exact source JSON download, executed-proposal recovery, expired unexecuted recheck and paper-review totals were exercised in the isolated instance. Screenshots are saved outside the checkout in the current task visualization directory.
- Frontend: VUI contracts, API contract, TypeScript/build, same-line controls and 1280/1920 browser acceptance.
- Integration: self-review each stable delivery, managed closeout and local fast-forward integration; official shared runtime is refreshed only through the authorized Launcher flow.
- Version/refresh decision: additive finance APIs and UI, with compatible paper-account data; no release or remote publication is part of this task. The shared runtime needs a later Launcher rebuild/restart to consume the change. Isolated runtime verification does not establish deployment to that shared instance.

## Reuse decision

Adapt the local paper ledger, report export, stateless LLM adapter and task primitives. Reference TradingAgents-CN risk-manager separation at pinned commit `51060a7682cf51810b4bc3a704829438d18cd8dc`; no restricted application source is copied and no additional dependency is required. Public descriptions of other projects guide capability comparison, not verified performance claims.

## Portfolio backtest contract for the next delivery

Keep the existing frozen-data worker, one model call per decision date, budget fences and stop/resume semantics. Add a versioned basket snapshot with normalized symbols, per-asset hashes and an identical explicit session calendar; missing bars remain a hard failure. Simulate one shared cash account, next-open execution, sells before buys, then buys in canonical symbol order with the same cash constraint and disclosed ordering. Retain the existing per-position cap semantics and add a separate gross-exposure limit if needed.

Use the same frozen basket as an equal-weight buy-and-hold benchmark, with identical fees, slippage and lot rules. A constituent that cannot fill retains its cash allocation and records the failed order; never silently drop it. Freeze the optional out-of-sample start date before a run. Report the continuous account before and after that boundary, using the previous close as the out-of-sample starting equity; do not reset capital or tune on that period. Preserve old single-stock inputs and stored runs through explicit adapters.

The basket engine and window evaluator have passed focused accounting and no-future regressions. Independent review identified a benchmark entry one session earlier than the strategy; both now start at the same next-open boundary, including the earliest holdout baseline. Historical buy-side stamp duty is reserved before sizing both single-stock and basket benchmark purchases.

Isolated acceptance on 2026-10-09 used Tencent raw data for sh600036/sz000001 on 2026-09-28 through 2026-09-30, with a frozen 2026-09-30 holdout boundary. A real Qwen model first exercised a cash-only strategy. A separate fixed-allocation execution probe was stopped after its first accepted decision, then resumed after an official Launcher restart. Data/parameter hashes, token counts and the accepted decision survived; only the remaining decision was called. Four simulated fills left cash 100092.20 from initial 100000, with fees 83.80. Replaying the original start request returned the same run, calls, trades and cash. Browser JSON/CSV downloads were parsed and cross-checked, including all per-symbol position columns and cash conservation. Both 1280x900 and 1920x1080 retained the desktop three-column layout without horizontal document overflow. This short probe validates execution, not investment performance.

The original September 21-25 range was correctly blocked by a raw/qfq transformation change in sz000001 on September 24. No data guard was bypassed. Historical evidence cutoff guards were separately reviewed, tested through the real ToolExecutor and integrated locally; undated or future financial evidence cannot enter historical model tool output, and the external financial RAG query remains unavailable for historical requests without publication provenance. This does not yet supply a complete point-in-time fundamentals archive.

Next comparison delivery will reference ordinary independent runs and reuse frozen snapshots for candidate previews. Comparison reads must reject differing data, holdout boundaries or execution assumptions; existing per-run budget, stop/resume and unknown-call handling remain authoritative. No nested multi-arm worker or second job subsystem is needed.
