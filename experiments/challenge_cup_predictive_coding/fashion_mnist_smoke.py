"""Bounded FashionMNIST reconstruction smoke for the Challenge Cup research lane."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


INFERENCE_LATENT_CORRECTION = "inference_latent_correction"
MASKED_PREDICTION_ERROR_TRAINING = "masked_prediction_error_training"


@dataclass(frozen=True)
class ExperimentConfig:
    seed: int = 42
    train_samples: int = 4096
    test_samples: int = 1024
    epochs: int = 2
    batch_size: int = 64
    latent_dim: int = 32
    learning_rate: float = 1e-3
    correction_steps: int = 3
    correction_rate: float = 0.8
    mask_size: int = 8
    num_workers: int = 0
    candidate_mechanism: str = INFERENCE_LATENT_CORRECTION
    candidate_masked_loss_weight: float = 4.0
    minimum_mse_improvement: float = 0.001
    maximum_latency_multiplier: float = 5.0
    maximum_global_mse_regression: float = 0.0005


def _torch_modules():
    try:
        import torch
        from torch import nn
        from torch.utils.data import DataLoader, Subset
        from torchvision import transforms
        from torchvision.datasets import FashionMNIST
    except (ImportError, OSError) as exc:  # pragma: no cover - environment gate
        raise RuntimeError(
            "PyTorch experiment environment is unavailable. Use the pinned CPU environment from README.md."
        ) from exc
    return torch, nn, DataLoader, Subset, transforms, FashionMNIST


def set_determinism(seed: int) -> Any:
    torch, *_ = _torch_modules()
    random.seed(seed)
    torch.manual_seed(seed)
    torch.use_deterministic_algorithms(True)
    torch.set_num_threads(max(1, min(4, torch.get_num_threads())))
    return torch.Generator().manual_seed(seed)


def build_model(latent_dim: int):
    torch, nn, *_ = _torch_modules()

    class SmallAutoencoder(nn.Module):
        def __init__(self) -> None:
            super().__init__()
            self.encoder_conv = nn.Sequential(
                nn.Conv2d(1, 8, 3, stride=2, padding=1),
                nn.ReLU(),
                nn.Conv2d(8, 16, 3, stride=2, padding=1),
                nn.ReLU(),
            )
            self.encoder_linear = nn.Linear(16 * 7 * 7, latent_dim)
            self.decoder_linear = nn.Linear(latent_dim, 16 * 7 * 7)
            self.decoder_conv = nn.Sequential(
                nn.ConvTranspose2d(16, 8, 3, stride=2, padding=1, output_padding=1),
                nn.ReLU(),
                nn.ConvTranspose2d(8, 1, 3, stride=2, padding=1, output_padding=1),
                nn.Sigmoid(),
            )

        def encode(self, images):
            features = self.encoder_conv(images)
            return self.encoder_linear(features.flatten(1))

        def decode(self, latent):
            features = self.decoder_linear(latent).reshape(-1, 16, 7, 7)
            return self.decoder_conv(features)

        def forward(self, images):
            return self.decode(self.encode(images))

    return SmallAutoencoder()


def structured_mask(images, *, generator, mask_size: int):
    torch, *_ = _torch_modules()
    mask = torch.ones_like(images)
    limit = int(images.shape[-1]) - mask_size + 1
    tops = torch.randint(0, limit, (len(images),), generator=generator)
    lefts = torch.randint(0, limit, (len(images),), generator=generator)
    for index, (top, left) in enumerate(zip(tops.tolist(), lefts.tolist())):
        mask[index, :, top : top + mask_size, left : left + mask_size] = 0.0
    return images * mask, mask


def corrected_reconstruction(model, corrupted, observed_mask, *, steps: int, correction_rate: float):
    torch, *_ = _torch_modules()
    latent = model.encode(corrupted).detach()
    for _ in range(steps):
        latent.requires_grad_(True)
        prediction = model.decode(latent)
        visible_error = ((prediction - corrupted) * observed_mask).pow(2).flatten(1).mean(dim=1).sum()
        gradient = torch.autograd.grad(visible_error, latent, only_inputs=True)[0]
        latent = (latent - correction_rate * gradient).detach()
    return model.decode(latent)


def _fixed_subset(dataset, count: int, *, seed: int):
    torch, _, _, Subset, *_ = _torch_modules()
    if count > len(dataset):
        raise ValueError(f"requested {count} samples from dataset of size {len(dataset)}")
    indices = torch.randperm(len(dataset), generator=torch.Generator().manual_seed(seed))[:count].tolist()
    return Subset(dataset, indices)


def load_data(config: ExperimentConfig, data_root: Path):
    torch, _, DataLoader, _, transforms, FashionMNIST = _torch_modules()
    transform = transforms.ToTensor()
    train_dataset = FashionMNIST(data_root, train=True, download=False, transform=transform)
    test_dataset = FashionMNIST(data_root, train=False, download=False, transform=transform)
    train_subset = _fixed_subset(train_dataset, config.train_samples, seed=config.seed)
    test_subset = _fixed_subset(test_dataset, config.test_samples, seed=config.seed + 1)
    train_loader = DataLoader(
        train_subset,
        batch_size=config.batch_size,
        shuffle=True,
        generator=torch.Generator().manual_seed(config.seed + 2),
        num_workers=config.num_workers,
    )
    test_loader = DataLoader(test_subset, batch_size=config.batch_size, shuffle=False, num_workers=config.num_workers)
    return train_loader, test_loader


def train(
    model,
    train_loader,
    config: ExperimentConfig,
    *,
    masked_loss_weight: float = 0.0,
) -> list[float]:
    torch, nn, *_ = _torch_modules()
    optimizer = torch.optim.Adam(model.parameters(), lr=config.learning_rate)
    loss_fn = nn.MSELoss()
    corruption_generator = torch.Generator().manual_seed(config.seed + 10)
    epoch_losses: list[float] = []
    model.train()
    for _ in range(config.epochs):
        total_loss = 0.0
        total_samples = 0
        for clean, _ in train_loader:
            corrupted, observed_mask = structured_mask(
                clean,
                generator=corruption_generator,
                mask_size=config.mask_size,
            )
            optimizer.zero_grad(set_to_none=True)
            reconstruction = model(corrupted)
            if masked_loss_weight > 0:
                missing_mask = 1.0 - observed_mask
                pixel_weights = 1.0 + (masked_loss_weight * missing_mask)
                loss = ((reconstruction - clean).pow(2) * pixel_weights).sum() / pixel_weights.sum()
            else:
                loss = loss_fn(reconstruction, clean)
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(clean)
            total_samples += len(clean)
        epoch_losses.append(round(total_loss / max(total_samples, 1), 8))
    return epoch_losses


def _evaluate_models(baseline_model, candidate_model, test_loader, config: ExperimentConfig) -> dict[str, Any]:
    torch, *_ = _torch_modules()
    corruption_generator = torch.Generator().manual_seed(config.seed + 20)
    totals = {key: 0.0 for key in ("baseline", "variant", "baseline_masked", "variant_masked")}
    sample_count = 0
    masked_pixel_count = 0.0
    baseline_seconds = 0.0
    variant_seconds = 0.0
    baseline_model.eval()
    candidate_model.eval()
    for clean, _ in test_loader:
        corrupted, observed_mask = structured_mask(clean, generator=corruption_generator, mask_size=config.mask_size)
        missing_mask = 1.0 - observed_mask
        start = time.perf_counter()
        with torch.no_grad():
            baseline = baseline_model(corrupted)
        baseline_seconds += time.perf_counter() - start
        start = time.perf_counter()
        with torch.no_grad():
            variant = candidate_model(corrupted)
        variant_seconds += time.perf_counter() - start
        totals["baseline"] += float((baseline - clean).pow(2).sum())
        totals["variant"] += float((variant - clean).pow(2).sum())
        totals["baseline_masked"] += float(((baseline - clean).pow(2) * missing_mask).sum())
        totals["variant_masked"] += float(((variant - clean).pow(2) * missing_mask).sum())
        sample_count += len(clean)
        masked_pixel_count += float(missing_mask.sum())
    all_pixels = sample_count * 28 * 28
    baseline_mse = totals["baseline"] / all_pixels
    variant_mse = totals["variant"] / all_pixels
    baseline_masked_mse = totals["baseline_masked"] / masked_pixel_count
    variant_masked_mse = totals["variant_masked"] / masked_pixel_count
    return {
        "baseline": {
            "reconstruction_mse": round(baseline_mse, 8),
            "masked_region_mse": round(baseline_masked_mse, 8),
            "seconds": round(baseline_seconds, 6),
        },
        "variant": {
            "reconstruction_mse": round(variant_mse, 8),
            "masked_region_mse": round(variant_masked_mse, 8),
            "seconds": round(variant_seconds, 6),
        },
        "delta": {
            "mse_improvement": round(baseline_mse - variant_mse, 8),
            "masked_mse_improvement": round(baseline_masked_mse - variant_masked_mse, 8),
            "latency_multiplier": round(variant_seconds / max(baseline_seconds, 1e-9), 4),
        },
        "test_samples": sample_count,
    }


def evaluate(model, test_loader, config: ExperimentConfig) -> dict[str, Any]:
    if config.candidate_mechanism == MASKED_PREDICTION_ERROR_TRAINING:
        raise ValueError("masked prediction-error evaluation requires separate baseline and candidate models")
    torch, *_ = _torch_modules()
    corruption_generator = torch.Generator().manual_seed(config.seed + 20)
    totals = {key: 0.0 for key in ("baseline", "variant", "baseline_masked", "variant_masked")}
    sample_count = 0
    masked_pixel_count = 0.0
    baseline_seconds = 0.0
    variant_seconds = 0.0
    model.eval()
    for clean, _ in test_loader:
        corrupted, observed_mask = structured_mask(clean, generator=corruption_generator, mask_size=config.mask_size)
        missing_mask = 1.0 - observed_mask
        start = time.perf_counter()
        with torch.no_grad():
            baseline = model(corrupted)
        baseline_seconds += time.perf_counter() - start
        start = time.perf_counter()
        variant = corrected_reconstruction(
            model,
            corrupted,
            observed_mask,
            steps=config.correction_steps,
            correction_rate=config.correction_rate,
        )
        variant_seconds += time.perf_counter() - start
        totals["baseline"] += float((baseline - clean).pow(2).sum())
        totals["variant"] += float((variant - clean).pow(2).sum())
        totals["baseline_masked"] += float(((baseline - clean).pow(2) * missing_mask).sum())
        totals["variant_masked"] += float(((variant - clean).pow(2) * missing_mask).sum())
        sample_count += len(clean)
        masked_pixel_count += float(missing_mask.sum())
    all_pixels = sample_count * 28 * 28
    baseline_mse = totals["baseline"] / all_pixels
    variant_mse = totals["variant"] / all_pixels
    baseline_masked_mse = totals["baseline_masked"] / masked_pixel_count
    variant_masked_mse = totals["variant_masked"] / masked_pixel_count
    return {
        "baseline": {
            "reconstruction_mse": round(baseline_mse, 8),
            "masked_region_mse": round(baseline_masked_mse, 8),
            "seconds": round(baseline_seconds, 6),
        },
        "variant": {
            "reconstruction_mse": round(variant_mse, 8),
            "masked_region_mse": round(variant_masked_mse, 8),
            "seconds": round(variant_seconds, 6),
        },
        "delta": {
            "mse_improvement": round(baseline_mse - variant_mse, 8),
            "masked_mse_improvement": round(baseline_masked_mse - variant_masked_mse, 8),
            "latency_multiplier": round(variant_seconds / max(baseline_seconds, 1e-9), 4),
        },
        "test_samples": sample_count,
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return f"sha256:{digest.hexdigest()}"


def _state_dict_hash(model) -> str:
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode("utf-8"))
        digest.update(str(tensor.dtype).encode("ascii"))
        digest.update(str(tuple(tensor.shape)).encode("ascii"))
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return f"sha256:{digest.hexdigest()}"


def stable_metric_payload(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "baseline": {
            "reconstruction_mse": metrics["baseline"]["reconstruction_mse"],
            "masked_region_mse": metrics["baseline"]["masked_region_mse"],
        },
        "variant": {
            "reconstruction_mse": metrics["variant"]["reconstruction_mse"],
            "masked_region_mse": metrics["variant"]["masked_region_mse"],
        },
        "delta": {
            "mse_improvement": metrics["delta"]["mse_improvement"],
            "masked_mse_improvement": metrics["delta"]["masked_mse_improvement"],
        },
        "test_samples": metrics["test_samples"],
    }


def classify_decision(metrics: dict[str, Any], config: ExperimentConfig) -> dict[str, Any]:
    delta = metrics.get("delta") if isinstance(metrics.get("delta"), dict) else {}
    metric_name = (
        "masked_mse_improvement"
        if config.candidate_mechanism == MASKED_PREDICTION_ERROR_TRAINING
        else "mse_improvement"
    )
    improvement = float(delta.get(metric_name) or 0.0)
    global_improvement = float(delta.get("mse_improvement") or 0.0)
    latency_multiplier = float(delta.get("latency_multiplier") or float("inf"))
    improvement_passed = improvement >= config.minimum_mse_improvement
    latency_passed = latency_multiplier <= config.maximum_latency_multiplier
    global_regression_passed = global_improvement >= -config.maximum_global_mse_regression
    return {
        "status": "support" if improvement_passed and latency_passed and global_regression_passed else "inconclusive",
        "primaryImprovementMetric": metric_name,
        "improvementPassed": improvement_passed,
        "latencyPassed": latency_passed,
        "globalRegressionPassed": global_regression_passed,
        "minimumMseImprovement": config.minimum_mse_improvement,
        "maximumLatencyMultiplier": config.maximum_latency_multiplier,
        "maximumGlobalMseRegression": config.maximum_global_mse_regression,
        "observedMseImprovement": improvement,
        "observedGlobalMseImprovement": global_improvement,
        "observedLatencyMultiplier": latency_multiplier,
    }


def run(config: ExperimentConfig, *, data_root: Path, output_dir: Path) -> dict[str, Any]:
    torch, *_ = _torch_modules()
    set_determinism(config.seed)
    train_loader, test_loader = load_data(config, data_root)
    baseline_model = build_model(config.latent_dim)
    initial_state = {
        name: tensor.detach().clone()
        for name, tensor in baseline_model.state_dict().items()
    }
    candidate_model = baseline_model
    started = time.perf_counter()
    baseline_epoch_losses = train(baseline_model, train_loader, config)
    baseline_training_seconds = time.perf_counter() - started
    candidate_epoch_losses: list[float] = []
    candidate_training_seconds = 0.0
    shared_weights = True
    if config.candidate_mechanism == MASKED_PREDICTION_ERROR_TRAINING:
        candidate_model = build_model(config.latent_dim)
        candidate_model.load_state_dict(initial_state)
        candidate_train_loader, _ = load_data(config, data_root)
        started = time.perf_counter()
        candidate_epoch_losses = train(
            candidate_model,
            candidate_train_loader,
            config,
            masked_loss_weight=config.candidate_masked_loss_weight,
        )
        candidate_training_seconds = time.perf_counter() - started
        metrics = _evaluate_models(baseline_model, candidate_model, test_loader, config)
        shared_weights = False
    elif config.candidate_mechanism == INFERENCE_LATENT_CORRECTION:
        metrics = evaluate(baseline_model, test_loader, config)
    else:
        raise ValueError(f"unsupported candidate mechanism: {config.candidate_mechanism}")
    decision = classify_decision(metrics, config)
    output_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_path = output_dir / "fashion_mnist_autoencoder.pt"
    torch.save({"model_state": baseline_model.state_dict(), "config": asdict(config)}, checkpoint_path)
    candidate_checkpoint_path = output_dir / "fashion_mnist_candidate.pt"
    if candidate_model is not baseline_model:
        torch.save({"model_state": candidate_model.state_dict(), "config": asdict(config)}, candidate_checkpoint_path)
    checkpoint_hash = _sha256_file(checkpoint_path)
    candidate_checkpoint_hash = (
        _sha256_file(candidate_checkpoint_path)
        if candidate_checkpoint_path.is_file()
        else checkpoint_hash
    )
    model_state_hash = _state_dict_hash(baseline_model)
    candidate_model_state_hash = _state_dict_hash(candidate_model)
    result = {
        "schemaVersion": 2,
        "status": "completed",
        "dataset": "FashionMNIST",
        "datasetProtocol": {
            "source": "torchvision.datasets.FashionMNIST",
            "trainSamples": config.train_samples,
            "testSamples": config.test_samples,
            "fixedSubset": True,
            "structuredMaskSize": config.mask_size,
        },
        "config": asdict(config),
        "model": {
            "name": "SmallAutoencoder",
            "parameterCount": sum(parameter.numel() for parameter in baseline_model.parameters()),
            "sharedWeightsBetweenBaselineAndVariant": shared_weights,
            "matchedArchitectureAndParameterCount": True,
            "candidateMechanism": config.candidate_mechanism,
        },
        "training": {
            "baselineEpochLosses": baseline_epoch_losses,
            "candidateEpochLosses": candidate_epoch_losses,
            "baselineSeconds": round(baseline_training_seconds, 6),
            "candidateSeconds": round(candidate_training_seconds, 6),
            "matchedEpochAndBatchBudget": True,
        },
        "metrics": metrics,
        "checkpoint": {
            "path": str(checkpoint_path),
            "sha256": checkpoint_hash,
            "modelStateSha256": model_state_hash,
            "candidatePath": str(candidate_checkpoint_path) if candidate_checkpoint_path.is_file() else str(checkpoint_path),
            "candidateSha256": candidate_checkpoint_hash,
            "candidateModelStateSha256": candidate_model_state_hash,
        },
        "decision": decision,
        "boundaries": [
            "single_seed_smoke_only",
            "fixed_subset_not_full_dataset",
            "does_not_validate_neural_realism",
            "full_run_requires_multi_seed_review",
        ],
        "versions": {"python": sys.version.split()[0], "torch": torch.__version__},
    }
    hash_payload = json.dumps(
        {
            "config": result["config"],
            "metrics": stable_metric_payload(result["metrics"]),
            "modelStateSha256": model_state_hash,
            "candidateModelStateSha256": candidate_model_state_hash,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    result["artifactHash"] = f"sha256:{hashlib.sha256(hash_payload.encode('utf-8')).hexdigest()}"
    result_path = output_dir / "result.json"
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    result["resultPath"] = str(result_path)
    return result


def self_check() -> None:
    torch, *_ = _torch_modules()
    set_determinism(7)
    model = build_model(8)
    clean = torch.linspace(0.0, 1.0, steps=2 * 28 * 28).reshape(2, 1, 28, 28)
    corrupted, mask = structured_mask(clean, generator=torch.Generator().manual_seed(7), mask_size=6)
    baseline = model(corrupted)
    variant = corrected_reconstruction(model, corrupted, mask, steps=2, correction_rate=0.5)
    assert baseline.shape == clean.shape == variant.shape
    assert torch.isfinite(variant).all()
    print(json.dumps({"status": "ok", "baselineShape": list(baseline.shape), "torch": torch.__version__}))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output-dir", type=Path)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--train-samples", type=int, default=4096)
    parser.add_argument("--test-samples", type=int, default=1024)
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--correction-steps", type=int, default=3)
    parser.add_argument("--correction-rate", type=float, default=0.8)
    parser.add_argument(
        "--candidate-mechanism",
        choices=(INFERENCE_LATENT_CORRECTION, MASKED_PREDICTION_ERROR_TRAINING),
        default=INFERENCE_LATENT_CORRECTION,
    )
    parser.add_argument("--candidate-masked-loss-weight", type=float, default=4.0)
    parser.add_argument("--minimum-mse-improvement", type=float, default=0.001)
    parser.add_argument("--maximum-latency-multiplier", type=float, default=5.0)
    parser.add_argument("--maximum-global-mse-regression", type=float, default=0.0005)
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.self_check:
        self_check()
        return
    if args.data_root is None or args.output_dir is None:
        raise SystemExit("--data-root and --output-dir are required unless --self-check is used")
    config = ExperimentConfig(
        seed=args.seed,
        train_samples=args.train_samples,
        test_samples=args.test_samples,
        epochs=args.epochs,
        batch_size=args.batch_size,
        correction_steps=args.correction_steps,
        correction_rate=args.correction_rate,
        candidate_mechanism=args.candidate_mechanism,
        candidate_masked_loss_weight=args.candidate_masked_loss_weight,
        minimum_mse_improvement=args.minimum_mse_improvement,
        maximum_latency_multiplier=args.maximum_latency_multiplier,
        maximum_global_mse_regression=args.maximum_global_mse_regression,
    )
    result = run(config, data_root=args.data_root, output_dir=args.output_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
