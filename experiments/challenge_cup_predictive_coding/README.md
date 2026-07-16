# FashionMNIST predictive-coding smoke

This is a bounded CPU experiment for the Challenge Cup research lane. It compares one shared-weight autoencoder in two inference modes:

- baseline: one forward reconstruction;
- variant: three latent updates driven by reconstruction residual on visible pixels.

The smoke uses a fixed FashionMNIST subset, seed `42`, two epochs, and an `8x8` structured mask. It does not establish neural realism or replace a multi-seed/full-dataset evaluation.

Create the isolated environment outside the application environment:

```powershell
$root = "C:\Users\17533\Documents\Vibelution\data\experiments\predictive_coding_mnist"
py -3 -m venv "$root\.venv"
& "$root\.venv\Scripts\python.exe" -m pip install -r "experiments\challenge_cup_predictive_coding\requirements-cpu.lock"
```

Download FashionMNIST once through `torchvision.datasets.FashionMNIST`, then run:

```powershell
& "$root\.venv\Scripts\python.exe" "experiments\challenge_cup_predictive_coding\fashion_mnist_smoke.py" `
  --data-root "$root\data" `
  --output-dir "$root\runs\seed-42" `
  --seed 42 --train-samples 4096 --test-samples 1024 --epochs 2 --correction-steps 3
```

Artifacts are written outside the repository under the supplied output directory.
