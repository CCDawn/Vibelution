"""CPU 确定性 Smoke Runner（PRD N-11 / V1）。

设计边界（与 PRD「白名单 runner」一致）：
- 仅运行平台内置白名单 adapter；不联网、不执行任意用户代码、不触发 GPU 训练。
- 固定 seed → 可复现：同一 (adapter, seed, threshold) 产生完全相同的 metrics 与 artifactHash。
- 仅依赖 numpy（项目已装），刻意不引入 scikit-learn；sklearn adapter 作为后续增量
  （需先把 scikit-learn 加入 requirements）。

输出 RunnerResult 形态：baseline / variant / delta / threshold + artifactHash + decisionHint。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

import numpy as np

RUNNER_MODE = "v1_cpu_smoke"
CLASSIFICATION_ADAPTER = "synthetic_classification_baseline_vs_variant"
RECONSTRUCTION_PROXY_ADAPTER = "predictive_coding_reconstruction_proxy"
WHITELIST_ADAPTERS = (CLASSIFICATION_ADAPTER, RECONSTRUCTION_PROXY_ADAPTER)
NON_EXECUTABLE_ADAPTERS = ("literature_review_smoke",)
DEFAULT_THRESHOLD = 0.01


class SmokeRunnerError(ValueError):
    """非法 adapter 或非法 runner 请求。"""


def _make_synthetic_classification(seed: int, *, n_samples: int = 240, n_features: int = 12, n_classes: int = 3):
    rng = np.random.default_rng(seed)
    centers = rng.normal(0.0, 3.0, size=(n_classes, n_features))
    labels = rng.integers(0, n_classes, size=n_samples)
    features = centers[labels] + rng.normal(0.0, 1.0, size=(n_samples, n_features))
    n_train = int(n_samples * 0.8)
    return features[:n_train], labels[:n_train], features[n_train:], labels[n_train:]


def _nearest_centroid_predict(x_train, y_train, x_test, *, scale: bool = False):
    classes = np.unique(y_train)
    if scale:
        std = x_train.std(axis=0)
        std[std == 0] = 1.0
        x_train = x_train / std
        x_test = x_test / std
    centroids = np.stack([x_train[y_train == cls].mean(axis=0) for cls in classes])
    distances = ((x_test[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
    return classes[distances.argmin(axis=1)]


def _classification_metrics(y_true, y_pred) -> dict[str, float]:
    accuracy = float((y_true == y_pred).mean())
    f1_scores: list[float] = []
    for cls in np.unique(y_true):
        true_pos = int(((y_pred == cls) & (y_true == cls)).sum())
        false_pos = int(((y_pred == cls) & (y_true != cls)).sum())
        false_neg = int(((y_pred != cls) & (y_true == cls)).sum())
        precision = true_pos / (true_pos + false_pos) if (true_pos + false_pos) else 0.0
        recall = true_pos / (true_pos + false_neg) if (true_pos + false_neg) else 0.0
        f1_scores.append((2 * precision * recall / (precision + recall)) if (precision + recall) else 0.0)
    macro_f1 = float(np.mean(f1_scores)) if f1_scores else 0.0
    return {"accuracy": round(accuracy, 6), "macro_f1": round(macro_f1, 6)}


def _make_structured_reconstruction_proxy(seed: int, *, n_samples: int = 256):
    """Build deterministic 8x8 patterns without downloading target datasets."""
    rng = np.random.default_rng(seed)
    bases: list[np.ndarray] = []
    for row in (1, 3, 5, 6):
        pattern = np.zeros((8, 8), dtype=float)
        pattern[row, 1:7] = 1.0
        bases.append(pattern)
    for column in (1, 3, 5, 6):
        pattern = np.zeros((8, 8), dtype=float)
        pattern[1:7, column] = 1.0
        bases.append(pattern)
    bases.extend((np.eye(8, dtype=float), np.fliplr(np.eye(8, dtype=float))))
    basis = np.stack(bases).reshape(len(bases), -1)
    weights = np.zeros((n_samples, len(bases)), dtype=float)
    for sample_index in range(n_samples):
        active = rng.choice(len(bases), size=int(rng.integers(2, 5)), replace=False)
        weights[sample_index, active] = rng.uniform(0.45, 1.0, size=len(active))
    clean = np.clip(weights @ basis + rng.normal(0.0, 0.025, size=(n_samples, 64)), 0.0, 1.0)
    n_train = int(n_samples * 0.8)
    test = clean[n_train:]
    observed_mask = np.ones_like(test)
    for sample_index in range(len(test)):
        top = int(rng.integers(1, 5))
        left = int(rng.integers(1, 5))
        observed_mask[sample_index, :].reshape(8, 8)[top : top + 3, left : left + 3] = 0.0
    corrupted = np.clip(test * observed_mask + rng.normal(0.0, 0.04, size=test.shape) * observed_mask, 0.0, 1.0)
    return clean[:n_train], test, corrupted, observed_mask


def _pca_reconstruction_basis(train: np.ndarray, *, rank: int = 12) -> tuple[np.ndarray, np.ndarray]:
    mean = train.mean(axis=0)
    _, _, right = np.linalg.svd(train - mean, full_matrices=False)
    return mean, right[:rank]


def _predictive_coding_proxy_metrics(seed: int, *, correction_steps: int = 3) -> tuple[dict[str, Any], dict[str, Any]]:
    train, clean, corrupted, observed_mask = _make_structured_reconstruction_proxy(seed)
    mean, components = _pca_reconstruction_basis(train)
    latent = (corrupted - mean) @ components.T
    baseline = np.clip(mean + latent @ components, 0.0, 1.0)
    corrected_latent = latent.copy()
    visible_fraction = np.maximum(observed_mask.mean(axis=1, keepdims=True), 1e-6)
    for _ in range(correction_steps):
        prediction = mean + corrected_latent @ components
        visible_residual = (corrupted - prediction) * observed_mask
        corrected_latent += 0.65 * (visible_residual @ components.T) / visible_fraction
    variant = np.clip(mean + corrected_latent @ components, 0.0, 1.0)

    missing_mask = 1.0 - observed_mask

    def reconstruction_metrics(reconstruction: np.ndarray) -> dict[str, float]:
        all_mse = float(np.mean((reconstruction - clean) ** 2))
        missing_mse = float(np.sum(((reconstruction - clean) ** 2) * missing_mask) / np.sum(missing_mask))
        return {"reconstruction_mse": round(all_mse, 6), "masked_region_mse": round(missing_mse, 6)}

    baseline_metrics = reconstruction_metrics(baseline)
    variant_metrics = reconstruction_metrics(variant)
    delta = {
        "reconstruction_mse": round(variant_metrics["reconstruction_mse"] - baseline_metrics["reconstruction_mse"], 6),
        "masked_region_mse": round(variant_metrics["masked_region_mse"] - baseline_metrics["masked_region_mse"], 6),
        "mse_improvement": round(baseline_metrics["reconstruction_mse"] - variant_metrics["reconstruction_mse"], 6),
    }
    return {"baseline": baseline_metrics, "variant": variant_metrics, "delta": delta}, {
        "trainSamples": len(train),
        "testSamples": len(clean),
        "imageShape": [8, 8],
        "pcaRank": len(components),
        "correctionSteps": correction_steps,
        "maskedPixelsPerSample": 9,
    }


def _decision_hint(macro_delta: float, threshold: float) -> str:
    if macro_delta >= threshold:
        return "accept" if macro_delta >= threshold * 2 else "iterate"
    if macro_delta <= -threshold:
        return "reject"
    return "needs_full_run"


def _artifact_hash(config: dict[str, Any], metrics: dict[str, Any], logs: str) -> str:
    digest = hashlib.sha256(
        (json.dumps(config, sort_keys=True) + json.dumps(metrics, sort_keys=True) + logs).encode("utf-8")
    ).hexdigest()
    return f"sha256:{digest}"


def run_smoke_adapter(
    adapter: str,
    *,
    seed: int = 42,
    threshold: float | None = None,
    baseline_config: dict[str, Any] | None = None,
    variant_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """运行一个白名单 smoke adapter，返回确定性 RunnerResult。

    - ``literature_review_smoke``：非执行型，仅返回 non_executable 占位（证据一致性检查在别处做）。
    - ``synthetic_classification_baseline_vs_variant``：numpy 合成数据上 baseline(最近质心) vs
      variant(特征缩放后最近质心)，固定 seed、固定 80/20 切分。
    """
    normalized_adapter = str(adapter or "").strip()
    if normalized_adapter in NON_EXECUTABLE_ADAPTERS:
        return {
            "adapter": normalized_adapter,
            "runnerMode": RUNNER_MODE,
            "seed": int(seed),
            "status": "non_executable",
            "executable": False,
            "metrics": {},
            "decisionHint": "needs_full_run",
            "note": "literature_review_smoke 仅做证据一致性检查，不可执行。",
        }
    if normalized_adapter not in WHITELIST_ADAPTERS:
        raise SmokeRunnerError(f"adapter not in whitelist: {normalized_adapter!r}")

    seed_int = int(seed)
    if normalized_adapter == RECONSTRUCTION_PROXY_ADAPTER:
        threshold_value = float(threshold) if threshold is not None else 0.001
        metrics, proxy_config = _predictive_coding_proxy_metrics(seed_int)
        metrics["threshold"] = {"mse_improvement": threshold_value}
        improvement = float(metrics["delta"]["mse_improvement"])
        decision_hint = _decision_hint(improvement, threshold_value)
        config = {
            "adapter": normalized_adapter,
            "runnerMode": RUNNER_MODE,
            "seed": seed_int,
            "dataset": "synthetic_structured_8x8_proxy",
            "targetDataset": "MNIST/Fashion-MNIST",
            "proxyOnly": True,
            "baselineConfig": baseline_config or {"model": "one_shot_pca_reconstruction"},
            "variantConfig": variant_config
            or {"model": "iterative_visible_residual_correction", "correctionSteps": proxy_config["correctionSteps"]},
            **proxy_config,
        }
        logs = (
            f"adapter={normalized_adapter} seed={seed_int} proxy_only=true "
            f"baseline={metrics['baseline']} variant={metrics['variant']} "
            f"delta={metrics['delta']} decision={decision_hint}"
        )
        return {
            "adapter": normalized_adapter,
            "runnerMode": RUNNER_MODE,
            "seed": seed_int,
            "status": "completed",
            "executable": True,
            "proxyOnly": True,
            "metrics": metrics,
            "config": config,
            "logs": logs,
            "artifactHash": _artifact_hash(config, metrics, logs),
            "decisionHint": decision_hint,
            "boundaries": [
                "offline_numpy_only",
                "does_not_replace_target_dataset_evaluation",
                "does_not_validate_neural_realism",
                "no_full_run_promotion_from_proxy_only",
            ],
        }

    threshold_value = float(threshold) if threshold is not None else DEFAULT_THRESHOLD
    x_train, y_train, x_test, y_test = _make_synthetic_classification(seed_int)
    baseline_pred = _nearest_centroid_predict(x_train, y_train, x_test, scale=False)
    variant_pred = _nearest_centroid_predict(x_train, y_train, x_test, scale=True)
    baseline_metrics = _classification_metrics(y_test, baseline_pred)
    variant_metrics = _classification_metrics(y_test, variant_pred)
    delta = {key: round(variant_metrics[key] - baseline_metrics[key], 6) for key in baseline_metrics}
    decision_hint = _decision_hint(delta.get("macro_f1", 0.0), threshold_value)

    metrics = {
        "baseline": baseline_metrics,
        "variant": variant_metrics,
        "delta": delta,
        "threshold": {"macro_f1": threshold_value},
    }
    config = {
        "adapter": normalized_adapter,
        "runnerMode": RUNNER_MODE,
        "seed": seed_int,
        "datasetSplit": "fixed_80_20",
        "baselineConfig": baseline_config or {"model": "nearest_centroid"},
        "variantConfig": variant_config or {"model": "nearest_centroid", "featureScaling": True},
    }
    logs = (
        f"adapter={normalized_adapter} seed={seed_int} "
        f"baseline={baseline_metrics} variant={variant_metrics} delta={delta} decision={decision_hint}"
    )
    return {
        "adapter": normalized_adapter,
        "runnerMode": RUNNER_MODE,
        "seed": seed_int,
        "status": "completed",
        "executable": True,
        "metrics": metrics,
        "config": config,
        "logs": logs,
        "artifactHash": _artifact_hash(config, metrics, logs),
        "decisionHint": decision_hint,
    }
