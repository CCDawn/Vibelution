# Financial workspace preferences

The public facade remains `financial_preferences_service.py`. Its text preferences
continue to use canonical personal memory. `workspace.py` owns structured desktop
settings: selected stock, watchlist tags/notes, reusable research profiles, manual
holdings, review bookmarks and an optional investment profile. These user settings are not a second transcript,
report store, broker connection or financial-account ledger.

State lives inside the owner-checked financial Agent private artifacts boundary.
Updates merge only explicitly supplied sections under a cross-process lock and
require the current revision. Corrupt files fail closed without replacement.
Quotes, generated reports and market valuations are always read from their
existing authorities; only identifiers and user-authored settings are persisted.

`investmentProfile` is a nullable section replaced as a whole on PATCH. Missing
numeric/boolean fields remain unknown (`null`); market defaults to `CN` and holdings
status to `unknown`. Old workspace files read as `investmentProfile: null`. The
active, ready financial assistant reads the latest private settings each turn,
including when episodic memory is disabled; failures forbid reusing old amounts.

`availableCashCny` is a separately confirmed actual cash balance; budget does not
imply cash. `investmentPlans` is server-owned, bounded to 20 records and excluded
from generic PATCH. The additive `/workspace/advisor/proposal`, `/command` and
`/check` routes reuse this workspace and native Session identities. Old schema-1
files default to an empty plan list; reading does not write a migration.

`advisor_proposals.py` reads a single strict `investment-proposal` block only
from an owned, successfully completed native final answer. The proposal is data,
and is written only by the explicit user confirmation command. A semantic
fingerprint binds the proposal and plan to the current profile and holdings.
`needsReview` is recomputed from that fingerprint and the review time.
`advisor.py` owns revision-checked plan transitions and atomic user-confirmed
actual cash/position snapshots. Adoption never writes positions. These records
are user declarations, not broker transactions.

`advisor_calculator.py` uses Decimal, shared A-share quantity and fee rules and
provider quote timestamps. Missing/stale prices or unconfirmed cash/holdings
block adoption. Fees remain estimates; sellability is unknown without broker
evidence. Review dates are passive prompts, not scheduled jobs.
