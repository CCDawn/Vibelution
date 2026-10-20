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
