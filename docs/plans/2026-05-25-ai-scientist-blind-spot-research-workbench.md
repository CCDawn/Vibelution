# AI Scientist Blind Spot Research Workbench Implementation Plan

**Goal:** Upgrade Vibelution's existing `/research` page from a frontend-only preview into an AI Scientist research workbench that can run an evidence-grounded blind spot discovery workflow from source intake to candidate research questions, hypotheses, experiment plans, and supervised-evolution handoff.

**Architecture:** Add a new `core/research/` domain that owns durable AI Scientist research objects and pure workflow logic. Expose the domain through `core/web/routes/research.py` and `core/web/services/research_service.py`. Keep the React `ResearchRoute` as a dense workbench surface that reads/writes research projects through API calls and later hands approved experiment plans to existing Gym/Supervised Evolution boundaries.

**Tech Stack:** Python 3.11/3.12, FastAPI, Pydantic-style dataclasses or stdlib dataclasses, JSON persistence under `workspace/research/`, React + Vite + TanStack Query, existing Vibelution Core First and Workbench route conventions.

---

## 1. Product Behavior

### User-facing workflow

The Research page should guide one complete loop:

1. Create or select a **Research Project**.
2. Add **Sources**:
   - papers,
   - GitHub issues or repositories,
   - local Vibelution traces,
   - notes or human research goals.
3. Extract **Evidence Records** from sources.
4. Run six **Blind Spot Detectors**:
   - anomaly,
   - contradiction,
   - gap matrix,
   - boundary condition,
   - cross-domain transfer,
   - causal gap.
5. Produce **Problem Candidates** with novelty, verifiability, impact, evidence strength, and cross-domain transfer scores.
6. Promote selected problem candidates into **Hypothesis Cards**.
7. Convert approved hypotheses into **Experiment Plans** with baselines, metrics, source/target datasets, and falsification conditions.
8. Mark an experiment plan as ready for Vibelution **Supervised Evolution** handoff.
9. Record results as **Research Findings** and feed them back into the next loop.

### Safety boundaries

- The first implementation is advisory-only: it can create research artifacts and handoff proposals, but must not mutate baseline Agent behavior.
- Generated cases may enter `train` or `observe`, but must not automatically enter `holdout`.
- Every claim and hypothesis must keep provenance back to source, evidence, trace, human note, or experiment result.
- Qwen/Bailian calls are represented as a model profile requirement in the workflow, but the first slice can use deterministic local extractors and fixtures so tests remain stable.

## 2. Domain Model

Add `core/research/models.py` with these primary objects:

```python
ResearchProject(
    project_id: str,
    title: str,
    objective: str,
    domain: str,
    cross_domain_lens: list[str],
    status: Literal["draft", "active", "archived"],
    created_at: str,
    updated_at: str,
)

ResearchSource(
    source_id: str,
    project_id: str,
    kind: Literal["paper", "github", "trace", "note", "dataset"],
    title: str,
    locator: str,
    summary: str,
    added_at: str,
)

EvidenceRecord(
    evidence_id: str,
    project_id: str,
    source_id: str,
    claim: str,
    evidence_type: Literal["fact", "method", "metric", "failure", "result", "counterexample"],
    quote_or_pointer: str,
    confidence: float,
    capability_tags: list[str],
)

BlindSpotCandidate(
    candidate_id: str,
    project_id: str,
    detector: Literal["anomaly", "contradiction", "gap_matrix", "boundary", "cross_domain", "causal_gap"],
    title: str,
    problem_statement: str,
    novelty_score: float,
    verifiability_score: float,
    impact_score: float,
    evidence_strength: float,
    cross_domain_transfer_score: float,
    discovery_score: float,
    supporting_evidence_ids: list[str],
    status: Literal["draft", "shortlisted", "rejected", "promoted"],
)

HypothesisCard(
    hypothesis_id: str,
    project_id: str,
    candidate_id: str,
    hypothesis: str,
    mechanism: str,
    expected_effect: str,
    falsification_conditions: list[str],
    metrics: list[str],
    source_dataset: str,
    target_dataset: str,
    status: Literal["draft", "reviewing", "approved", "rejected"],
)

ExperimentPlan(
    experiment_id: str,
    project_id: str,
    hypothesis_id: str,
    title: str,
    baselines: list[str],
    candidate: str,
    dataset_splits: list[str],
    metrics: list[str],
    validation_steps: list[str],
    supervised_bundle_name: str,
    status: Literal["draft", "ready_for_handoff", "handed_off", "completed"],
)
```

## 3. Persistence

Use simple JSON files for v1:

```text
workspace/research/projects/<project_id>/project.json
workspace/research/projects/<project_id>/sources.json
workspace/research/projects/<project_id>/evidence.json
workspace/research/projects/<project_id>/blind_spots.json
workspace/research/projects/<project_id>/hypotheses.json
workspace/research/projects/<project_id>/experiments.json
workspace/research/projects/<project_id>/findings.json
```

This matches Vibelution's local-first posture and keeps the first release inspectable. If the object set grows, move to SQLite later; do not start with a database.

## 4. API Contract

Add a new router at `core/web/routes/research.py` with prefix included by `core/web/app.py` under `/api`.

Endpoints:

```text
GET  /api/research/overview
POST /api/research/projects
GET  /api/research/projects/{project_id}
POST /api/research/projects/{project_id}/sources
POST /api/research/projects/{project_id}/extract-evidence
POST /api/research/projects/{project_id}/discover-blind-spots
POST /api/research/projects/{project_id}/candidates/{candidate_id}/promote
POST /api/research/projects/{project_id}/hypotheses/{hypothesis_id}/approve
POST /api/research/projects/{project_id}/experiments
POST /api/research/projects/{project_id}/experiments/{experiment_id}/mark-ready
```

V1 response shape should include:

```json
{
  "project": {},
  "sources": [],
  "evidence": [],
  "blindSpotCandidates": [],
  "hypotheses": [],
  "experiments": [],
  "summary": {
    "sourceCount": 0,
    "evidenceCount": 0,
    "candidateCount": 0,
    "approvedHypothesisCount": 0,
    "readyExperimentCount": 0
  }
}
```

## 5. Workflow Logic

Add `core/research/blind_spots.py`.

Implement deterministic first-pass detectors:

1. `detect_anomalies(evidence)`
   - Finds repeated `failure` evidence with the same capability tags.
2. `detect_contradictions(evidence)`
   - Finds `method` evidence and `counterexample` or `failure` evidence with overlapping tags.
3. `detect_gap_matrix(evidence)`
   - Builds capability x phase coverage matrix and identifies sparse cells.
4. `detect_boundary_conditions(evidence)`
   - Finds evidence phrases indicating "works in simple tasks but fails in complex/long/multi-file tasks".
5. `detect_cross_domain_transfer(evidence, cross_domain_lens)`
   - Generates candidates when a lens such as `causal science`, `control theory`, or `metacognition` has no matching local mechanism evidence yet.
6. `detect_causal_gaps(evidence)`
   - Finds sequences like context failure -> patch failure -> test failure -> recovery failure and proposes missing causal mechanism problems.

Use a transparent scoring formula:

```python
discovery_score = (
    0.30 * novelty_score
    + 0.25 * verifiability_score
    + 0.20 * impact_score
    + 0.15 * evidence_strength
    + 0.10 * cross_domain_transfer_score
)
```

V1 scoring can be heuristic but must be deterministic and visible in the UI.

## 6. Frontend Design

Upgrade `web/src/routes/ResearchRoute.tsx` from preview to workbench.

Recommended layout:

```text
Top summary row:
Project, current stage, source count, candidate count, ready experiments

Left rail:
Project selector
Workflow stages:
1 Intake
2 Evidence
3 Blind Spots
4 Hypotheses
5 Experiments
6 Findings

Main panel:
Stage-specific table/cards

Right inspector:
Selected source/evidence/candidate/hypothesis/experiment detail
Provenance and next action
```

Initial v1 can remain dense and utilitarian. Do not build a marketing page.

Primary controls:

- `New project`
- `Add source`
- `Extract evidence`
- `Run blind spot discovery`
- `Shortlist candidate`
- `Promote to hypothesis`
- `Approve hypothesis`
- `Create experiment plan`
- `Mark ready for supervised handoff`

## 7. Integration With Supervised Evolution

Do not directly run supervised evolution in the first slice.

Instead:

- `ExperimentPlan.supervised_bundle_name` should suggest a bundle name such as `blind_spot_<slug>_v1`.
- `mark-ready` writes a handoff artifact:

```text
workspace/research/projects/<project_id>/handoff/<experiment_id>.json
```

The handoff JSON should include:

```json
{
  "experimentId": "...",
  "hypothesisId": "...",
  "suggestedBundleName": "...",
  "baselines": [],
  "candidate": "...",
  "metrics": [],
  "datasetSplits": ["dev", "holdout", "regression", "observe"],
  "sourceEvidenceIds": []
}
```

Later, add a `Dataset Adapter` that materializes approved experiment plans into Vibelution Cases.

## 8. Implementation Tasks

### Task 1: Add Research Domain Models

**Files:**
- Create: `core/research/__init__.py`
- Create: `core/research/models.py`
- Test: `tests/test_research_models.py`

**Steps:**
1. Write tests for constructing each model and serializing to/from dict.
2. Implement dataclasses or Pydantic-compatible models.
3. Add helper normalization for IDs and timestamps.
4. Run `pytest tests/test_research_models.py -q`.

### Task 2: Add JSON Repository

**Files:**
- Create: `core/research/repository.py`
- Test: `tests/test_research_repository.py`

**Steps:**
1. Write tests that use `tmp_path` to create a project, add sources, persist evidence, and reload.
2. Implement `ResearchRepository`.
3. Ensure all writes are atomic enough for local JSON use: write temp file then replace.
4. Run `pytest tests/test_research_repository.py -q`.

### Task 3: Implement Blind Spot Detectors

**Files:**
- Create: `core/research/blind_spots.py`
- Test: `tests/test_research_blind_spots.py`

**Steps:**
1. Write synthetic evidence fixtures for anomaly, contradiction, gap matrix, boundary, cross-domain, and causal gap.
2. Implement deterministic detector functions.
3. Implement `rank_candidates`.
4. Verify discovery score ordering.
5. Run `pytest tests/test_research_blind_spots.py -q`.

### Task 4: Add Research Service

**Files:**
- Create: `core/web/services/research_service.py`
- Test: `tests/test_research_service.py`

**Steps:**
1. Write service tests using temporary project root.
2. Implement overview, project creation, source add, evidence extraction, discovery, candidate promotion, hypothesis approval, experiment creation, ready marking.
3. Evidence extraction v1 can be deterministic:
   - notes become `fact`,
   - traces with "error", "failed", "test" become `failure`,
   - papers with "method", "metric", "baseline" become corresponding evidence types.
4. Run `pytest tests/test_research_service.py -q`.

### Task 5: Add Research API Routes

**Files:**
- Create: `core/web/routes/research.py`
- Modify: `core/web/app.py`
- Test: `tests/test_research_routes.py`

**Steps:**
1. Write FastAPI route tests using test client.
2. Include the router in `create_app`.
3. Return stable JSON shapes matching frontend types.
4. Run `pytest tests/test_research_routes.py -q`.
5. Run `pytest tests/test_web_app.py -q` to ensure existing app route behavior survives.

### Task 6: Add Frontend Types and Query Keys

**Files:**
- Modify: `web/src/api/types.ts`
- Modify: `web/src/api/queryKeys.ts`
- Test: existing TS compile/build

**Steps:**
1. Add `ResearchOverview`, `ResearchProject`, `ResearchSource`, `EvidenceRecord`, `BlindSpotCandidate`, `HypothesisCard`, `ExperimentPlan`.
2. Add query keys:
   - `researchOverview`
   - `researchProject(projectId)`
3. Run `cd web && npm run build`.

### Task 7: Upgrade ResearchRoute to Workbench UI

**Files:**
- Modify: `web/src/routes/ResearchRoute.tsx`
- Modify: `web/src/routes/ResearchRoute.module.css`
- Test: `web/src/routes/ResearchRoute.layout.test.ts`

**Steps:**
1. Update layout test to assert the six workflow stages and main controls.
2. Implement API-backed overview with TanStack Query.
3. Add stage tabs or rail.
4. Add source/evidence/candidate/hypothesis/experiment panels.
5. Keep empty states useful: show "create project" and "add source" guidance.
6. Run `cd web && npm run test -- ResearchRoute`.
7. Run `cd web && npm run build`.

### Task 8: Add Handoff Artifact UI

**Files:**
- Modify: `web/src/routes/ResearchRoute.tsx`
- Modify: `core/web/services/research_service.py`
- Test: `tests/test_research_service.py`, `web/src/routes/ResearchRoute.layout.test.ts`

**Steps:**
1. Add "Mark ready for supervised handoff" action.
2. Make service write `workspace/research/projects/<project_id>/handoff/<experiment_id>.json`.
3. UI should show artifact path and suggested bundle name.
4. Do not auto-run supervised evolution.

### Task 9: Documentation

**Files:**
- Modify: `README.md`
- Modify: `CONTEXT.md`
- Create: `docs/adr/XXXX-research-workbench-uses-advisory-handoff-before-supervised-materialization.md`

**Steps:**
1. Add Research page to README Web routes if needed.
2. Add domain terms to `CONTEXT.md` only if they become load-bearing:
   - Research Project
   - Evidence Record
   - Blind Spot Candidate
   - Hypothesis Card
   - Experiment Plan
3. Add ADR documenting advisory handoff before supervised materialization.

## 9. Testing Strategy

Backend:

```bash
pytest tests/test_research_models.py -q
pytest tests/test_research_repository.py -q
pytest tests/test_research_blind_spots.py -q
pytest tests/test_research_service.py -q
pytest tests/test_research_routes.py -q
pytest tests/test_web_app.py -q
```

Frontend:

```bash
cd web
npm run test -- ResearchRoute
npm run build
```

Manual:

1. Start workbench.
2. Open `/research`.
3. Create a project.
4. Add one note source and one trace-like source.
5. Extract evidence.
6. Run blind spot discovery.
7. Promote one candidate.
8. Create an experiment plan.
9. Mark it ready for supervised handoff.
10. Confirm JSON handoff artifact exists.

## 10. Milestones

### Milestone A: Advisory local workflow

Scope:
- Models,
- repository,
- deterministic detectors,
- routes,
- API-backed ResearchRoute.

Success:
- A user can complete source -> evidence -> blind spot -> hypothesis -> experiment plan inside `/research`.

### Milestone B: Qwen/Bailian-assisted extraction

Scope:
- Add model profile selection,
- add prompt templates,
- call Qwen for evidence extraction and hypothesis drafting,
- keep deterministic fallback for tests.

Success:
- A real project can use Qwen/Bailian to produce evidence and hypotheses, with call metadata saved.

### Milestone C: Supervised Evolution materialization

Scope:
- Add Dataset Adapter from approved experiment plans to Cases/Bundles.
- Add guarded "materialize bundle" action.

Success:
- An approved experiment plan can become a Vibelution supervised bundle without bypassing holdout/regression rules.

## 11. Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Research page becomes a disconnected demo | Put durable objects in `core/research`, not only React state. |
| Blind spot discovery appears magical | Show detector type, evidence IDs, and scores for every candidate. |
| Generated cases pollute holdout | Enforce generated cases default to train/observe only. |
| Qwen calls make tests unstable | Use deterministic extractors in unit tests and Qwen only behind service boundary. |
| Duplicate supervised evolution logic | Use handoff artifacts first; add Dataset Adapter later. |
| User assumes ready candidate is promoted | Label v1 as advisory; no baseline mutation from Research page. |

## 12. Open Questions

1. Should v1 support importing existing Vibelution trace files from `logs/runtime_scenes`, or only manual source entry first?
2. Should Qwen/Bailian be mandatory in v1, or introduced in Milestone B after deterministic workflow works?
3. Which cross-domain lenses should ship by default?
   - Recommended v1 defaults: `causal science`, `control theory`, `metacognition`, `reliability engineering`.

## 13. Recommended First Slice

Build Milestone A first. It creates a full usable research loop without external API risk:

```text
manual source -> deterministic evidence -> blind spot detectors -> ranked candidates -> hypothesis -> experiment plan -> handoff JSON
```

After that, add Qwen/Bailian calls to improve extraction and hypothesis writing while preserving the same object model and tests.
