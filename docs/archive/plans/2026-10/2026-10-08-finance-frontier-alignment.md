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
- First delivery: in progress. Accounting conservation, failed-batch rollback, stale-account rejection, approval replay, ownership isolation, T+1 and bounded market data tests are required.
- Frontend: VUI contracts, API contract, TypeScript/build, same-line controls and 1280/1920 browser acceptance.
- Integration: self-review each stable delivery, managed closeout and local fast-forward integration; official shared runtime is refreshed only through the authorized Launcher flow.

## Reuse decision

Adapt the local paper ledger, report export, stateless LLM adapter and task primitives. Reference TradingAgents-CN risk-manager separation at pinned commit `51060a7682cf51810b4bc3a704829438d18cd8dc`; no restricted application source is copied and no additional dependency is required. Public descriptions of other projects guide capability comparison, not verified performance claims.
