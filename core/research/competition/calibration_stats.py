"""Calibration statistics for the G12 gate (decision #13, frozen 2026-08-28).

Pure computation layer for the auto-advance calibration pilot: confusion
matrix aggregation, Cohen's kappa with a confidence interval, one-sided
upper bounds for the false-auto-approve rate, per-stratum statistics and
the activation gate assessment. No I/O, no state, no network; every
function is deterministic.

Method choices (documented per decision #13 required evidence):

- ``wilson`` upper bound: one-sided Wilson score interval, closed form
  (see :func:`false_auto_approve_upper_bound`).
- ``beta_binomial`` upper bound: posterior quantile under a Beta(1,1)
  uniform prior, i.e. posterior ``Beta(failures + 1, trials - failures +
  1)`` (the Laplace/uniform-prior bound). This is deliberately distinct
  from the Jeffreys Beta(0.5, 0.5) prior bound; the uniform prior is the
  more conservative of the two for small samples and requires no new
  dependency (inverse CDF implemented via a regularized incomplete beta
  continued fraction, not scipy -- the repo does not depend on scipy).
- kappa CI: large-sample asymptotic normal interval (Fleiss 1971
  approximation that treats the chance-agreement term ``pe`` as fixed),
  chosen over bootstrap because the layer must be deterministic and
  reproducible for evidence; at small pilot ``n`` the interval is
  optimistic, which is acceptable because approval additionally requires
  the (conservative) false-auto-approve upper bound to be controlled.
- Prevalence paradox: when marginals are heavily skewed (``pe >= 0.8``)
  kappa is known to understate agreement (Feinstein & Cicchetti 1990;
  Byrt, Bishop & Carlin 1993); the result carries an explicit warning
  flag instead of silently reporting a low kappa.

Field names intentionally mirror the frozen ``automation_policy``
``calibrationGate`` contract (``confusionMatrix`` / ``kappaWithCI`` /
``stratifiedBy`` / ``falseAutoApproveUpperBound`` with method values
``wilson`` | ``beta_binomial`` and ``side=one_sided_upper`` /
``notAPermanentDelegation``) so consumers can map results without this
module importing that contract.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from statistics import NormalDist
from typing import Any

AUTO_DECISION_AUTO_APPROVE = "auto_approve"
AUTO_DECISION_AUTO_ESCALATE = "auto_escalate"
HUMAN_DECISION_APPROVE = "approve"
HUMAN_DECISION_ESCALATE = "escalate"

#: One-sided upper bound methods; mirrors the frozen contract values.
UPPER_BOUND_METHODS: tuple[str, ...] = ("wilson", "beta_binomial")

#: Stratification axes required by decision #13 (risk AND domain).
STRATUM_AXES: tuple[str, ...] = ("risk_class", "domain")
CROSS_AXIS = "risk_class x domain"

DEFAULT_CONFIDENCE = 0.95
DEFAULT_UPPER_BOUND_METHOD = "wilson"

#: Strata below this sample size are reported as ``insufficient`` (fail
#: open to "not approvable") instead of raising.
DEFAULT_MIN_STRATUM_N = 30

#: Pilot totals at or below this size are explicitly marked as not
#: constituting a permanent delegation proof (decision #13).
PILOT_SAMPLE_SIZE_CEILING = 12

#: ``pe`` at or above this threshold indicates marginals skewed enough
#: that kappa understates agreement (prevalence paradox heuristic).
PREVALENCE_PARADOX_PE_THRESHOLD = 0.8

#: Kappa tiers for the gate: >=0.75 strong, [0.6, 0.75) acceptable,
#: <0.6 below gate (decision #13 wording: report kappa with CI and gate
#: on the tier).
KAPPA_STRONG_THRESHOLD = 0.75
KAPPA_ACCEPTABLE_THRESHOLD = 0.6

KAPPA_TIER_STRONG = "strong"
KAPPA_TIER_ACCEPTABLE = "acceptable"
KAPPA_TIER_BELOW_GATE = "below_gate"
KAPPA_TIER_UNDEFINED = "undefined"

COVERAGE_SUFFICIENT = "sufficient"
COVERAGE_INSUFFICIENT = "insufficient"

RECORD_ALIASES: dict[str, tuple[str, ...]] = {
    "auto_decision": ("autoDecision", "auto_decision"),
    "human_decision": ("humanDecision", "human_decision"),
    "risk_class": ("riskClass", "risk_class"),
    "domain": ("domain",),
}


class CalibrationStatsError(ValueError):
    """A calibration statistics input was malformed."""


# ---------------------------------------------------------------------------
# Regularized incomplete beta (pure stdlib; the repo has no scipy dependency)
# ---------------------------------------------------------------------------


def _betacf(a: float, b: float, x: float) -> float:
    """Continued fraction for the incomplete beta function (Lentz)."""
    tiny = 1e-300
    qab = a + b
    qap = a + 1.0
    qam = a - 1.0
    c = 1.0
    d = 1.0 - qab * x / qap
    if abs(d) < tiny:
        d = tiny
    d = 1.0 / d
    h = d
    for m in range(1, 500):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < tiny:
            d = tiny
        c = 1.0 + aa / c
        if abs(c) < tiny:
            c = tiny
        d = 1.0 / d
        delta = d * c
        h *= delta
        if abs(delta - 1.0) < 1e-15:
            break
    return h


def regularized_incomplete_beta(x: float, a: float, b: float) -> float:
    """Return ``I_x(a, b)``, the regularized incomplete beta function.

    Pure-stdlib implementation (continued fraction with the standard
    reflection symmetry); used to invert the Beta-binomial posterior.
    """
    if a <= 0 or b <= 0:
        raise CalibrationStatsError("beta parameters must be positive")
    if x < 0.0 or x > 1.0:
        raise CalibrationStatsError("beta CDF argument must be within [0, 1]")
    if x == 0.0:
        return 0.0
    if x == 1.0:
        return 1.0
    log_front = (
        math.lgamma(a + b)
        - math.lgamma(a)
        - math.lgamma(b)
        + a * math.log(x)
        + b * math.log1p(-x)
    )
    front = math.exp(log_front)
    if x < (a + 1.0) / (a + b + 2.0):
        return front * _betacf(a, b, x) / a
    return 1.0 - front * _betacf(b, a, 1.0 - x) / b


def beta_quantile(p: float, a: float, b: float) -> float:
    """Return the ``p``-quantile of the Beta(a, b) distribution.

    Bisection on the regularized incomplete beta CDF; deterministic to
    full double precision for the sample sizes a calibration pilot
    produces.
    """
    if not 0.0 < p < 1.0:
        raise CalibrationStatsError("quantile probability must be within (0, 1)")
    lo, hi = 0.0, 1.0
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if regularized_incomplete_beta(mid, a, b) < p:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-16:
            break
    return 0.5 * (lo + hi)


# ---------------------------------------------------------------------------
# Confusion matrix (positive class = "should escalate")
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ConfusionMatrix:
    """2x2 auto-vs-human decision matrix; positive class is escalate.

    ``true_positives``  auto escalated  and human escalated.
    ``false_positives`` auto escalated  but human approved  (false escalate).
    ``false_negatives`` auto approved   but human escalated (false auto
                        approve -- the critical error for decision #13).
    ``true_negatives``  auto approved   and human approved.
    """

    true_positives: int = 0
    false_positives: int = 0
    false_negatives: int = 0
    true_negatives: int = 0

    @property
    def total(self) -> int:
        return (
            self.true_positives
            + self.false_positives
            + self.false_negatives
            + self.true_negatives
        )

    @property
    def false_auto_approve_count(self) -> int:
        """Auto approved but the human decision was escalate (critical)."""
        return self.false_negatives

    @property
    def false_escalate_count(self) -> int:
        """Auto escalated but the human decision was approve."""
        return self.false_positives

    @property
    def observed_agreement(self) -> float:
        return (self.true_positives + self.true_negatives) / self.total

    @property
    def expected_agreement(self) -> float:
        total = self.total
        auto_escalate = self.true_positives + self.false_positives
        auto_approve = self.false_negatives + self.true_negatives
        human_escalate = self.true_positives + self.false_negatives
        human_approve = self.false_positives + self.true_negatives
        return (
            auto_escalate * human_escalate + auto_approve * human_approve
        ) / (total * total)

    @property
    def prevalence(self) -> float:
        """Share of items that should have been escalated."""
        if self.total == 0:
            return 0.0
        return (self.true_positives + self.false_negatives) / self.total

    def as_dict(self) -> dict[str, int]:
        return {
            "truePositives": self.true_positives,
            "falsePositives": self.false_positives,
            "falseNegatives": self.false_negatives,
            "trueNegatives": self.true_negatives,
            "falseAutoApproveCount": self.false_auto_approve_count,
            "falseEscalateCount": self.false_escalate_count,
        }


def _record_field(record: Mapping[str, Any], logical: str) -> str:
    for key in RECORD_ALIASES[logical]:
        if key in record and record[key] is not None:
            return str(record[key]).strip()
    raise CalibrationStatsError(
        f"calibration record is missing {logical!r}: keys={sorted(record)}"
    )


def normalize_risk_class(risk_class: str) -> str:
    """Normalize risk class spellings (``low_risk`` -> ``low``)."""
    normalized = str(risk_class or "").strip().lower().replace("-", "_")
    if normalized == "low_risk":
        return "low"
    if normalized == "high_risk":
        return "high"
    return normalized


def build_confusion_matrix(records: Sequence[Mapping[str, Any]]) -> ConfusionMatrix:
    """Aggregate per-question judgment records into the 2x2 matrix.

    Records carry ``autoDecision`` (``auto_approve`` | ``auto_escalate``),
    ``humanDecision`` (``approve`` | ``escalate``), ``riskClass`` and
    ``domain``. Unknown decision values fail closed: silently dropping a
    record would fabricate evidence.
    """
    tp = fp = fn = tn = 0
    for record in records:
        if not isinstance(record, Mapping):
            raise CalibrationStatsError(
                f"calibration record must be a mapping, got {type(record)!r}"
            )
        auto = _record_field(record, "auto_decision")
        human = _record_field(record, "human_decision")
        _record_field(record, "risk_class")
        _record_field(record, "domain")
        if auto == AUTO_DECISION_AUTO_APPROVE:
            if human == HUMAN_DECISION_APPROVE:
                tn += 1
            elif human == HUMAN_DECISION_ESCALATE:
                fn += 1
            else:
                raise CalibrationStatsError(
                    f"unknown humanDecision {human!r}; expected "
                    f"{HUMAN_DECISION_APPROVE!r} or {HUMAN_DECISION_ESCALATE!r}"
                )
        elif auto == AUTO_DECISION_AUTO_ESCALATE:
            if human == HUMAN_DECISION_APPROVE:
                fp += 1
            elif human == HUMAN_DECISION_ESCALATE:
                tp += 1
            else:
                raise CalibrationStatsError(
                    f"unknown humanDecision {human!r}; expected "
                    f"{HUMAN_DECISION_APPROVE!r} or {HUMAN_DECISION_ESCALATE!r}"
                )
        else:
            raise CalibrationStatsError(
                f"unknown autoDecision {auto!r}; expected "
                f"{AUTO_DECISION_AUTO_APPROVE!r} or {AUTO_DECISION_AUTO_ESCALATE!r}"
            )
    return ConfusionMatrix(
        true_positives=tp,
        false_positives=fp,
        false_negatives=fn,
        true_negatives=tn,
    )


# ---------------------------------------------------------------------------
# Cohen's kappa with confidence interval
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KappaResult:
    """Cohen's kappa point estimate with an asymptotic CI."""

    kappa: float | None
    ci_low: float | None
    ci_high: float | None
    defined: bool
    confidence: float
    observed_agreement: float
    expected_agreement: float
    tier: str
    prevalence_paradox_suspected: bool
    note: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "kappa": self.kappa,
            "ciLow": self.ci_low,
            "ciHigh": self.ci_high,
            "defined": self.defined,
            "confidence": self.confidence,
            "observedAgreement": self.observed_agreement,
            "expectedAgreement": self.expected_agreement,
            "tier": self.tier,
            "prevalenceParadoxSuspected": self.prevalence_paradox_suspected,
            "note": self.note,
        }


def kappa_tier(kappa: float | None) -> str:
    """Gate tier for a kappa point estimate (decision #13 thresholds)."""
    if kappa is None:
        return KAPPA_TIER_UNDEFINED
    if kappa >= KAPPA_STRONG_THRESHOLD:
        return KAPPA_TIER_STRONG
    if kappa >= KAPPA_ACCEPTABLE_THRESHOLD:
        return KAPPA_TIER_ACCEPTABLE
    return KAPPA_TIER_BELOW_GATE


def cohens_kappa_with_ci(
    matrix: ConfusionMatrix, confidence: float = DEFAULT_CONFIDENCE
) -> KappaResult:
    """Cohen's kappa for the auto-vs-human matrix with a normal CI.

    Uses the Fleiss (1971) large-sample variance that treats ``pe`` as
    fixed: ``SE = sqrt(p0 (1 - p0) / (n (1 - pe)^2))``. Deterministic by
    design (a bootstrap CI would make the evidence non-reproducible);
    at small pilot ``n`` the interval is optimistic, which the gate
    compensates for with the conservative false-auto-approve bound.

    Degenerate inputs (empty matrix, or zero marginal variance so that
    ``pe == 1``) return ``defined=False`` instead of dividing by zero;
    undefined kappa must read as "not approvable", never as a crash.
    """
    if not 0.0 < confidence < 1.0:
        raise CalibrationStatsError("confidence must be within (0, 1)")
    total = matrix.total
    if total == 0:
        return KappaResult(
            kappa=None,
            ci_low=None,
            ci_high=None,
            defined=False,
            confidence=confidence,
            observed_agreement=0.0,
            expected_agreement=0.0,
            tier=KAPPA_TIER_UNDEFINED,
            prevalence_paradox_suspected=False,
            note="kappa is undefined for an empty matrix; treat as not approvable",
        )
    p0 = matrix.observed_agreement
    pe = matrix.expected_agreement
    if pe >= 1.0:
        return KappaResult(
            kappa=None,
            ci_low=None,
            ci_high=None,
            defined=False,
            confidence=confidence,
            observed_agreement=p0,
            expected_agreement=pe,
            tier=KAPPA_TIER_UNDEFINED,
            prevalence_paradox_suspected=False,
            note=(
                "kappa is undefined for this matrix (empty sample or "
                "degenerate marginals with zero expected-disagreement "
                "variance); treat as not approvable"
            ),
        )
    kappa = (p0 - pe) / (1.0 - pe)
    z = NormalDist().inv_cdf(0.5 + confidence / 2.0)
    variance = (p0 * (1.0 - p0)) / (total * (1.0 - pe) ** 2)
    half_width = z * math.sqrt(variance)
    ci_low = max(-1.0, kappa - half_width)
    ci_high = min(1.0, kappa + half_width)
    paradox = pe >= PREVALENCE_PARADOX_PE_THRESHOLD
    note = ""
    if paradox:
        note = (
            "prevalence paradox suspected: expected agreement "
            f"pe={pe:.3f} >= {PREVALENCE_PARADOX_PE_THRESHOLD} because the "
            "decision marginals are heavily skewed, so this kappa likely "
            "understates agreement; read it together with the CI and the "
            "false-auto-approve bound (Feinstein & Cicchetti 1990)"
        )
    return KappaResult(
        kappa=kappa,
        ci_low=ci_low,
        ci_high=ci_high,
        defined=True,
        confidence=confidence,
        observed_agreement=p0,
        expected_agreement=pe,
        tier=kappa_tier(kappa),
        prevalence_paradox_suspected=paradox,
        note=note,
    )


# ---------------------------------------------------------------------------
# One-sided upper bound for the false-auto-approve rate
# ---------------------------------------------------------------------------


def false_auto_approve_upper_bound(
    trials: int,
    failures: int,
    method: str = DEFAULT_UPPER_BOUND_METHOD,
    confidence: float = DEFAULT_CONFIDENCE,
) -> float:
    """One-sided upper bound for the false-auto-approve rate.

    ``trials`` is the number of items auto-approved, ``failures`` the
    number of those the human would escalate. Returns the value ``u``
    such that the data are consistent with a true rate at most ``u``
    at the given one-sided confidence level.

    - ``method="wilson"``: one-sided Wilson score interval, closed form
      ``u = (phat + z^2/(2n) + z sqrt(phat(1-phat)/n + z^2/(4n^2))) /
      (1 + z^2/n)`` with ``z = Phi^-1(confidence)`` (one-sided; the
      familiar two-sided 95% interval uses z=1.96 per side instead).
    - ``method="beta_binomial"``: posterior quantile under a Beta(1,1)
      uniform prior, ``Beta(failures+1, trials-failures+1)`` at
      ``confidence`` (Laplace/uniform-prior rule; more conservative than
      the Jeffreys Beta(0.5, 0.5) rule for small samples, and dependency
      free -- inverted via :func:`beta_quantile`, not scipy).

    Empty input (``trials < 1``) fails closed with an error; strata are
    handled upstream by :func:`stratum_report`, which marks them
    insufficient instead of calling this function.
    """
    if method not in UPPER_BOUND_METHODS:
        raise CalibrationStatsError(
            f"unknown upper bound method {method!r}; expected one of "
            f"{UPPER_BOUND_METHODS}"
        )
    if not 0.0 < confidence < 1.0:
        raise CalibrationStatsError("confidence must be within (0, 1)")
    if not isinstance(trials, int) or isinstance(trials, bool) or trials < 1:
        raise CalibrationStatsError("trials must be a positive integer")
    if not isinstance(failures, int) or isinstance(failures, bool):
        raise CalibrationStatsError("failures must be an integer")
    if failures < 0 or failures > trials:
        raise CalibrationStatsError(
            f"failures must be within [0, trials]; got {failures}/{trials}"
        )
    if method == "wilson":
        z = NormalDist().inv_cdf(confidence)
        phat = failures / trials
        radicand = phat * (1.0 - phat) / trials + (z * z) / (4.0 * trials * trials)
        numerator = (
            phat + (z * z) / (2.0 * trials) + z * math.sqrt(radicand)
        )
        return numerator / (1.0 + (z * z) / trials)
    posterior_alpha = failures + 1.0
    posterior_beta = trials - failures + 1.0
    return beta_quantile(confidence, posterior_alpha, posterior_beta)


# ---------------------------------------------------------------------------
# Stratified report
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StratumStat:
    """Statistics for one stratum; insufficient strata fail open."""

    axis: str
    value: str
    sample_size: int
    matrix: ConfusionMatrix
    kappa: KappaResult | None
    upper_bound: float | None
    coverage: str
    insufficient_reasons: tuple[str, ...] = ()
    upper_bound_method: str = DEFAULT_UPPER_BOUND_METHOD
    confidence: float = DEFAULT_CONFIDENCE

    @property
    def sufficient(self) -> bool:
        return self.coverage == COVERAGE_SUFFICIENT

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "value": self.value,
            "sampleSize": self.sample_size,
            "confusionMatrix": self.matrix.as_dict(),
            "kappa": self.kappa.as_dict() if self.kappa is not None else None,
            "falseAutoApproveUpperBound": self.upper_bound,
            "coverage": self.coverage,
            "insufficientReasons": list(self.insufficient_reasons),
            "upperBoundMethod": self.upper_bound_method,
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class CalibrationStrataReport:
    """Decision #13 evidence bundle for one calibration pilot batch."""

    total_sample_size: int
    overall: StratumStat
    strata: tuple[StratumStat, ...] = field(default_factory=tuple)

    def strata_by_axis(self, axis: str) -> tuple[StratumStat, ...]:
        return tuple(stratum for stratum in self.strata if stratum.axis == axis)

    @property
    def cross_strata(self) -> tuple[StratumStat, ...]:
        """risk-class x domain cells; the units approval binds to."""
        return self.strata_by_axis(CROSS_AXIS)

    def as_dict(self) -> dict[str, Any]:
        return {
            "totalSampleSize": self.total_sample_size,
            "overall": self.overall.as_dict(),
            "strata": [stratum.as_dict() for stratum in self.strata],
            "stratifiedBy": list(STRATUM_AXES),
        }


def _stratum_stat(
    axis: str,
    value: str,
    records: Sequence[Mapping[str, Any]],
    min_stratum_n: int,
    method: str,
    confidence: float,
) -> StratumStat:
    matrix = build_confusion_matrix(records)
    n = matrix.total
    reasons: list[str] = []
    if n < min_stratum_n:
        reasons.append(
            f"sample size {n} below required minimum {min_stratum_n}"
        )
    kappa = cohens_kappa_with_ci(matrix, confidence=confidence)
    if not kappa.defined:
        reasons.append("kappa undefined (empty or degenerate matrix)")
    auto_approved = matrix.true_negatives + matrix.false_negatives
    if not reasons and auto_approved == 0:
        reasons.append(
            "stratum contains no auto-approved items, so the "
            "false-auto-approve rate is not estimable"
        )
    if reasons:
        # Fail open to "not approvable": report nothing instead of a
        # bound that small samples would massively understate.
        return StratumStat(
            axis=axis,
            value=value,
            sample_size=n,
            matrix=matrix,
            kappa=kappa,
            upper_bound=None,
            coverage=COVERAGE_INSUFFICIENT,
            insufficient_reasons=tuple(reasons),
            upper_bound_method=method,
            confidence=confidence,
        )
    bound = false_auto_approve_upper_bound(
        trials=auto_approved,
        failures=matrix.false_negatives,
        method=method,
        confidence=confidence,
    )
    return StratumStat(
        axis=axis,
        value=value,
        sample_size=n,
        matrix=matrix,
        kappa=kappa,
        upper_bound=bound,
        coverage=COVERAGE_SUFFICIENT,
        upper_bound_method=method,
        confidence=confidence,
    )


def stratum_report(
    records: Sequence[Mapping[str, Any]],
    min_stratum_n: int = DEFAULT_MIN_STRATUM_N,
    method: str = DEFAULT_UPPER_BOUND_METHOD,
    confidence: float = DEFAULT_CONFIDENCE,
) -> CalibrationStrataReport:
    """Aggregate a pilot batch into overall + stratified statistics.

    Strata are cut along ``risk_class`` and ``domain`` (decision #13
    requires both axes) and on the cross product, because approval is
    per stratum and an aggregate pass never justifies a high-risk or
    uncovered cell. Strata below ``min_stratum_n`` are reported with
    ``coverage="insufficient"`` (fail open to "not approvable") rather
    than raising or producing an underpowered bound.
    """
    if method not in UPPER_BOUND_METHODS:
        raise CalibrationStatsError(
            f"unknown upper bound method {method!r}; expected one of "
            f"{UPPER_BOUND_METHODS}"
        )
    if not 0.0 < confidence < 1.0:
        raise CalibrationStatsError("confidence must be within (0, 1)")
    if not isinstance(min_stratum_n, int) or min_stratum_n < 1:
        raise CalibrationStatsError("min_stratum_n must be a positive integer")
    overall = _stratum_stat(
        "overall", "overall", records, min_stratum_n, method, confidence
    )
    grouped: dict[str, dict[str, list[Mapping[str, Any]]]] = {
        "risk_class": {},
        "domain": {},
        CROSS_AXIS: {},
    }
    for record in records:
        risk = normalize_risk_class(_record_field(record, "risk_class"))
        domain = _record_field(record, "domain")
        grouped["risk_class"].setdefault(risk, []).append(record)
        grouped["domain"].setdefault(domain, []).append(record)
        grouped[CROSS_AXIS].setdefault((risk, domain), []).append(record)
    strata: list[StratumStat] = []
    for axis in STRATUM_AXES + (CROSS_AXIS,):
        for value, group in grouped[axis].items():
            label = (
                f"{value[0]} x {value[1]}" if isinstance(value, tuple) else value
            )
            strata.append(
                _stratum_stat(axis, label, group, min_stratum_n, method, confidence)
            )
    return CalibrationStrataReport(
        total_sample_size=overall.sample_size,
        overall=overall,
        strata=tuple(strata),
    )


# ---------------------------------------------------------------------------
# Activation gate assessment (decision #13)
# ---------------------------------------------------------------------------

DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND = 0.05
DEFAULT_MIN_KAPPA = KAPPA_ACCEPTABLE_THRESHOLD
DEFAULT_APPROVABLE_RISK_CLASSES: tuple[str, ...] = ("low",)


@dataclass(frozen=True)
class StratumVerdict:
    """Approval verdict for one cross stratum (approval binds per stratum)."""

    axis: str
    value: str
    risk_class: str
    approvable: bool
    reasons: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "axis": self.axis,
            "value": self.value,
            "riskClass": self.risk_class,
            "approvable": self.approvable,
            "reasons": list(self.reasons),
        }


@dataclass(frozen=True)
class ActivationGateAssessment:
    """Gate outcome; ``not_permanent_delegation`` is always True (#13)."""

    approved: bool
    approvable_strata: tuple[str, ...]
    verdicts: tuple[StratumVerdict, ...]
    not_permanent_delegation: bool
    pilot_sample_size: int
    notes: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "approved": self.approved,
            "approvableStrata": list(self.approvable_strata),
            "verdicts": [verdict.as_dict() for verdict in self.verdicts],
            "notAPermanentDelegation": self.not_permanent_delegation,
            "pilotSampleSize": self.pilot_sample_size,
            "notes": list(self.notes),
        }


def _policy_value(policy: Mapping[str, Any], *names: str, default: Any) -> Any:
    """Duck-typed policy read: camelCase contract names with fallbacks."""
    for name in names:
        if name in policy and policy[name] is not None:
            return policy[name]
    return default


def activation_gate_assessment(
    report: CalibrationStrataReport, policy: Mapping[str, Any] | None = None
) -> ActivationGateAssessment:
    """Assess which strata the calibration pilot may delegate.

    Only strata that (a) belong to an approvable risk class, (b) have
    sufficient sample coverage, (c) hold a defined kappa at or above
    ``minKappa``, and (d) keep the false-auto-approve one-sided upper
    bound at or below ``maxFalseAutoApproveUpperBound`` are approvable;
    everything else fails closed to "not approvable". Per decision #13
    the result always carries ``not_permanent_delegation=True`` -- with
    special emphasis when the pilot has n <= 12, which by itself never
    constitutes a delegation proof.

    ``policy`` is a loose dict (camelCase keys mirroring the frozen
    ``calibrationGate`` contract, snake_case accepted); this module
    intentionally does not import ``automation_policy``.
    """
    policy = policy or {}
    max_bound = float(
        _policy_value(
            policy,
            "maxFalseAutoApproveUpperBound",
            "max_false_auto_approve_upper_bound",
            default=DEFAULT_MAX_FALSE_AUTO_APPROVE_UPPER_BOUND,
        )
    )
    min_kappa = float(
        _policy_value(
            policy,
            "minKappa",
            "min_kappa",
            default=DEFAULT_MIN_KAPPA,
        )
    )
    approvable_classes = {
        normalize_risk_class(str(item))
        for item in _policy_value(
            policy,
            "approvableRiskClasses",
            "approvable_risk_classes",
            default=list(DEFAULT_APPROVABLE_RISK_CLASSES),
        )
    }
    notes: list[str] = []
    verdicts: list[StratumVerdict] = []
    approvable_strata: list[str] = []
    for stratum in report.cross_strata:
        parts = [part.strip() for part in stratum.value.split(" x ")]
        risk = normalize_risk_class(parts[0]) if parts else ""
        reasons: list[str] = []
        if risk not in approvable_classes:
            reasons.append(
                f"risk class {risk!r} is not in approvable classes "
                f"{sorted(approvable_classes)}"
            )
        if stratum.insufficient_reasons:
            reasons.extend(stratum.insufficient_reasons)
        else:
            kappa = stratum.kappa
            assert kappa is not None and kappa.defined
            if kappa.kappa is None or kappa.kappa < min_kappa:
                reasons.append(
                    f"kappa {kappa.kappa!r} below required minimum {min_kappa}"
                )
            assert stratum.upper_bound is not None
            if stratum.upper_bound > max_bound:
                reasons.append(
                    f"false-auto-approve upper bound {stratum.upper_bound!r} "
                    f"exceeds maximum {max_bound!r}"
                )
        approvable = not reasons
        label = stratum.value
        if approvable:
            approvable_strata.append(label)
        else:
            notes.append(f"stratum {label!r} not approvable: " + "; ".join(reasons))
        verdicts.append(
            StratumVerdict(
                axis=stratum.axis,
                value=stratum.value,
                risk_class=risk,
                approvable=approvable,
                reasons=tuple(reasons),
            )
        )
    approved = bool(approvable_strata)
    notes.insert(
        0,
        "approval is per stratum; aggregate overall numbers never justify "
        "a high-risk or uncovered stratum (decision #13)",
    )
    if report.total_sample_size <= PILOT_SAMPLE_SIZE_CEILING:
        notes.insert(
            1,
            f"pilot sample size {report.total_sample_size} <= "
            f"{PILOT_SAMPLE_SIZE_CEILING}: this result explicitly does not "
            "constitute a permanent delegation proof (decision #13)",
        )
    return ActivationGateAssessment(
        approved=approved,
        approvable_strata=tuple(approvable_strata),
        verdicts=tuple(verdicts),
        not_permanent_delegation=True,
        pilot_sample_size=report.total_sample_size,
        notes=tuple(notes),
    )
