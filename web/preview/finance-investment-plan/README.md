# Investment configuration and plan preview

Isolated approval surface for the finance Agent. No production route, API,
Agent preference, paper ledger, model call or order is changed.

Run from `web`: `node node_modules/vite/bin/vite.js --config preview/finance-investment-plan/vite.config.ts`.
Local entry: `http://127.0.0.1:5208/preview/finance-investment-plan/index.html`.

Uses existing VUI controls, VDenseOpsPage and shared theme. No new VUI elements.
Layout is scoped to this preview, with stacked forms below 760px.

Initial user facts: approximate CNY 6000 budget, A shares, six-month observation
window with optional continued holding. Risk cap, reserve, concentration,
objective, holdings and permissions stay unconfirmed. Never translate the
user's willingness to tolerate more than CNY 600 volatility into a loss cap.

The explicit demo button fills *sample* assumptions. Fictitious candidate names,
fixed prices and equal initial allocations show the report shape, not investment
recommendations. Integer cents account for sample buy commissions and transfer
fees; allocation respects the configured cash reserve and concentration.
Loss scenarios are price changes only and are not a bound on actual losses.
Objective/horizon are snapshot text in this prototype, not model inputs.
Configuration is in React state only; reload discards it.

States: incomplete conditions, invalid numbers, existing holdings not yet entered,
generating, result, no affordable lot, changed-config stale report, missing
financial evidence, quote-service failure. Earlier reports retain their frozen
input snapshot until explicitly re-generated.

Approval boundary: production integration remains pending visual review.
After approval, extend existing finance workspace config and submit boundaries;
use server-owned quantities/fees and immutable plan inputs, not this fixture
calculator. Preserve legacy preferences/ledger and ordinary Session behavior.
