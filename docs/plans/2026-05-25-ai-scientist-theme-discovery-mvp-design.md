# AI Scientist Theme Discovery MVP Design

Date: 2026-05-25

## Goal

Upgrade Vibelution's existing `/research` page from a static research-flow preview into a first-stage AI Scientist theme discovery workbench.

The first MVP is intentionally scoped to finding a strong research theme. It does not implement the full experiment loop yet.

The workbench should help a user start from an open research goal and constraints, run two-stage online research, compare five novelty-oriented candidate themes, select one theme, and generate a concept-level theme card.

## Locked Scope

### In scope

1. Open goal and constraint intake.
2. Two-stage online search:
   - broad search for domain mapping,
   - deep search for promising intersections.
3. Sources from:
   - papers,
   - GitHub,
   - datasets,
   - general web pages.
4. Evidence extraction with source reliability and confidence.
5. Candidate theme generation.
6. Novelty-first scoring.
7. Similarity de-duplication.
8. Default output of five candidate themes.
9. Agent collaborator self-review for each candidate.
10. Persistent, reviewable research sessions.
11. Theme selection.
12. Concept-level theme card generation.
13. Stage rerun with conservative stale marking.

### Out of scope for this MVP

1. Full scientific hypothesis and experiment plan generation.
2. Experiment execution.
3. Supervised Evolution handoff.
4. Vibelution agent self-improvement as the research object.
5. Automatic baseline mutation.
6. Automatic holdout dataset entry.
7. A separate model configuration system.

## Product Behavior

### Main flow

```text
Open goal + constraints
  -> Broad online search
  -> Domain map
  -> High-potential intersections
  -> Deep online search
  -> Evidence extraction
  -> Candidate theme pool
  -> Novelty-first scoring
  -> Similarity de-duplication
  -> Five candidate themes
  -> User selects theme
  -> Concept-level theme card
```

### User input

The first screen should collect an opportunity discovery task, not a fixed research project.

Required fields:

- open goal,
- constraints,
- preferences.

Recommended defaults:

```text
Open goal:
Find a novel interdisciplinary AI Scientist research theme related to computer science.

Constraints:
Suitable for a student team, can be investigated with public sources, can become a competition MVP, and should fit the XH-202619 AI Scientist topic.

Preferences:
Novel, evidence-grounded, interdisciplinary, verifiable enough for a first-stage plan, and not a generic RAG or literature-review tool.
```

### Candidate count

Default output is exactly five candidate themes.

The system may internally generate more candidates, such as 12 to 20, then rank and de-duplicate before presenting the final five.

## Novelty-First Scoring

The MVP prioritizes novelty over ease of implementation.

```text
recommendation_score =
0.25 * novelty_gap
+ 0.20 * scientific_value
+ 0.15 * technical_depth
+ 0.15 * interdisciplinary_authenticity
+ 0.10 * verifiability
+ 0.10 * competition_fit
+ 0.05 * implementation_feasibility
```

### Novelty priority order

When judging novelty, the system should prioritize:

1. problem perspective novelty,
2. method-transfer novelty,
3. discipline-combination novelty,
4. application-scenario novelty.

The system should avoid treating a rare discipline pairing as sufficient novelty unless it creates a real scientific question or method transfer.

### Candidate theme fields

Each candidate theme should include:

- theme id,
- title,
- one-line positioning,
- interdisciplinary combination,
- core scientific question,
- novelty path,
- why it may be valuable,
- why it fits the competition,
- likely datasets or validation evidence,
- possible methods,
- possible baseline or comparison direction,
- source ids,
- evidence ids,
- score breakdown,
- recommendation score,
- uncertainty and risk notes,
- Agent collaborator review.

## Source and Evidence Rules

### Source reliability

```text
verified:
Paper database, official GitHub repository, dataset page, official documentation.

normal:
General web page, blog, news article, intro page.

weak:
Forum, Q&A, repost, incomplete summary page.
```

### Evidence confidence

```text
high:
The source is explicit and directly supports the claim.

medium:
The source is relevant, but the conclusion needs an inference bridge.

low:
The source is only a clue and cannot support a conclusion alone.
```

### Language boundary

Allowed wording:

- current search suggests,
- current evidence supports,
- current evidence does not show sufficient coverage,
- candidate research gap,
- needs further literature confirmation.

Disallowed wording unless directly proven:

- humans have never discovered this,
- already proven,
- must be effective,
- definitely innovative.

## Agent Collaborator View

In this MVP, the Agent is an executor and research collaborator. It is not yet the default research object.

For every candidate theme and selected theme card, the Agent should explain:

- why it recommends the theme,
- strongest evidence,
- main evidence gaps,
- uncertainty level,
- why the theme is or is not scientifically interesting,
- what should be investigated next.

The Agent review must not automatically change the selected theme status.

## State Model

### Discovery session

```python
ResearchDiscoverySession(
    session_id: str,
    open_goal: str,
    constraints: str,
    preferences: str,
    candidate_count: int,
    status: Literal["draft", "running", "reviewing", "selected", "archived", "failed"],
    created_at: str,
    updated_at: str,
    selected_theme_id: str | None,
)
```

### Search run

```python
SearchRun(
    run_id: str,
    session_id: str,
    phase: Literal["broad", "deep"],
    queries: list[str],
    provider: str,
    status: Literal["draft", "running", "completed", "failed"],
    started_at: str,
    completed_at: str | None,
    model_profile: dict,
)
```

### Research source

```python
ResearchSource(
    source_id: str,
    session_id: str,
    search_run_id: str,
    kind: Literal["paper", "github", "dataset", "web"],
    title: str,
    url: str,
    snippet: str,
    reliability: Literal["verified", "normal", "weak"],
    retrieved_at: str,
)
```

### Evidence record

```python
EvidenceRecord(
    evidence_id: str,
    session_id: str,
    source_id: str,
    claim: str,
    evidence_type: Literal["method", "dataset", "result", "gap", "implementation", "background"],
    confidence: Literal["high", "medium", "low"],
    note: str,
)
```

### Candidate theme

```python
CandidateTheme(
    theme_id: str,
    session_id: str,
    title: str,
    one_line: str,
    interdisciplinary_combination: list[str],
    core_question: str,
    novelty_path: Literal["problem_perspective", "method_transfer", "discipline_combination", "application_scenario"],
    scores: dict[str, float],
    recommendation_score: float,
    source_ids: list[str],
    evidence_ids: list[str],
    uncertainty: str,
    agent_review: str,
    status: Literal["draft", "shortlisted", "selected", "rejected", "stale"],
    version: int,
    parent_run_id: str,
)
```

### Theme card

```python
ThemeCard(
    card_id: str,
    session_id: str,
    theme_id: str,
    title: str,
    one_line: str,
    core_scientific_question: str,
    why_novel: str,
    why_competition_fit: str,
    interdisciplinary_combination: list[str],
    possible_datasets: list[str],
    possible_methods: list[str],
    possible_experiments: list[str],
    risks: list[str],
    references: list[str],
    next_research_steps: list[str],
    agent_review: str,
    status: Literal["draft", "approved", "stale"],
    version: int,
)
```

## Persistence

Use JSON persistence first.

```text
workspace/research/theme_discovery/sessions/<session_id>/session.json
workspace/research/theme_discovery/sessions/<session_id>/search_runs.json
workspace/research/theme_discovery/sessions/<session_id>/sources.json
workspace/research/theme_discovery/sessions/<session_id>/evidence.json
workspace/research/theme_discovery/sessions/<session_id>/candidate_themes.json
workspace/research/theme_discovery/sessions/<session_id>/theme_cards.json
workspace/research/theme_discovery/sessions/<session_id>/events.json
```

All generated artifacts should include:

- run id,
- version,
- created at,
- model profile,
- input snapshot,
- status,
- parent artifact id where useful.

## Rerun Behavior

Each major stage can be rerun:

- broad search,
- deep search,
- evidence extraction,
- candidate theme generation,
- theme card generation.

Reruns use conservative stale marking:

- do not delete downstream artifacts,
- do not overwrite approved artifacts,
- mark downstream artifacts as `stale` if they depend on older input,
- allow the user to keep, regenerate, reject, or re-approve stale artifacts.

## API Contract

Add a new router under `/api/research`.

```text
GET  /api/research/theme-discovery/sessions
POST /api/research/theme-discovery/sessions
GET  /api/research/theme-discovery/sessions/{session_id}
POST /api/research/theme-discovery/sessions/{session_id}/run-broad-search
POST /api/research/theme-discovery/sessions/{session_id}/run-deep-search
POST /api/research/theme-discovery/sessions/{session_id}/extract-evidence
POST /api/research/theme-discovery/sessions/{session_id}/generate-themes
POST /api/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/select
POST /api/research/theme-discovery/sessions/{session_id}/themes/{theme_id}/theme-card
POST /api/research/theme-discovery/sessions/{session_id}/theme-cards/{card_id}/approve
```

V1 may expose a combined action for one-click draft generation:

```text
POST /api/research/theme-discovery/sessions/{session_id}/run-draft
```

This action may run multiple stages, but all outputs remain draft or reviewing until the user selects or approves them.

## Frontend Behavior

Upgrade `web/src/routes/ResearchRoute.tsx`.

Recommended layout:

1. Left rail:
   - saved discovery sessions,
   - status,
   - selected theme if any.
2. Top input panel:
   - open goal,
   - constraints,
   - preferences,
   - create session,
   - run draft.
3. Stage timeline:
   - broad search,
   - deep search,
   - evidence,
   - candidate themes,
   - selected theme card.
4. Candidate comparison table:
   - title,
   - novelty path,
   - recommendation score,
   - score breakdown,
   - evidence coverage,
   - uncertainty,
   - select action.
5. Evidence/source panel:
   - papers,
   - GitHub,
   - datasets,
   - web.
6. Theme card panel:
   - concept-level selected theme card,
   - regenerate,
   - approve.

The visual style should remain a dense workbench, not a landing page.

## Search Provider Boundary

Implement provider abstraction first:

```python
class ResearchSearchProvider:
    def search_papers(self, query: str) -> list[SearchResult]: ...
    def search_github(self, query: str) -> list[SearchResult]: ...
    def search_datasets(self, query: str) -> list[SearchResult]: ...
    def search_web(self, query: str) -> list[SearchResult]: ...
```

The provider should be replaceable.

The Research page should reuse existing Vibelution model/provider configuration. It must not add a separate model settings page.

If live search is unavailable, the API should return a clear blocked or empty-evidence state rather than silently inventing results. Runtime search must not use deterministic fallback data; deterministic providers are allowed only in tests.

## BDD Scenarios

### Discover five themes

```gherkin
Scenario: Discover five novelty-oriented candidate themes
  Given the user enters an open research goal and constraints
  When the user runs theme discovery
  Then the system performs broad and deep search
  And the system collects paper, GitHub, dataset, and web sources
  And the system generates five candidate themes
  And the themes are ranked with novelty-first scoring
  And the themes are not near-duplicate variants of the same idea
```

### Select a theme

```gherkin
Scenario: Select a theme and generate a concept card
  Given the system has generated five candidate themes
  When the user selects one theme
  Then the selected theme is saved
  And the system generates a concept-level theme card
  And the card includes novelty, competition fit, possible datasets, possible methods, risks, references, and next research steps
```

### Rerun stage

```gherkin
Scenario: Rerun a stage without destroying downstream artifacts
  Given a session has candidate themes and a selected theme card
  When the user reruns deep search
  Then the system saves the new search run
  And downstream candidate themes or theme cards depending on old inputs are marked stale
  And no approved artifact is deleted automatically
```

### Persist session

```gherkin
Scenario: Reopen a previous discovery session
  Given the user has run a theme discovery session
  When the user returns to the research page later
  Then the session appears in the history list
  And the user can inspect inputs, searches, sources, evidence, candidate themes, scores, Agent reviews, and decisions
```

## Test Plan

Backend unit tests:

- scoring formula,
- novelty priority ordering,
- similarity de-duplication,
- stale marking,
- source reliability classification,
- evidence confidence handling.

Backend integration tests:

- save and load discovery session,
- run staged workflow with fake search provider,
- select theme and generate theme card,
- rerun stage marks downstream artifacts stale.

Route tests:

- create session,
- get session,
- generate themes,
- select theme,
- generate theme card,
- approve theme card.

Frontend tests:

- Research route no longer says frontend-only preview,
- renders discovery intake,
- renders five-theme comparison surface,
- renders source/evidence panels,
- renders selected theme card surface.

Manual verification:

- run the web app,
- create a discovery session,
- generate draft themes using fake or configured provider,
- select a theme,
- generate and approve a theme card,
- refresh page and reopen the session.

## Implementation Order

1. Add `core/research/` theme discovery models and scoring logic.
2. Add JSON repository.
3. Add fake/deterministic search provider for tests.
4. Add theme discovery service.
5. Add FastAPI route.
6. Add frontend API types.
7. Upgrade `ResearchRoute`.
8. Update frontend layout tests.
9. Run backend and frontend verification.

## BRT Result

- Locked behavior: Research page MVP discovers novel AI Scientist research themes and generates a concept-level theme card.
- Review blockers: none remaining.
- Main test anchor: five novelty-oriented, evidence-backed, de-duplicated candidate themes can be generated, persisted, reopened, selected, and converted into a theme card.
- Open issue: exact live search provider choice can be finalized during implementation behind the provider abstraction.
- Next step: implement the MVP behind `/api/research/theme-discovery`.
