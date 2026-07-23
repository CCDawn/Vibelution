# SCI-096 DANDI spike-coding probe

This bounded experiment compares a per-unit rate decoder with a capacity-matched
time-binned decoder on DANDI `000140`. It is an exploratory input to the
Challenge Cup hypothesis-revision loop, not evidence of a universal neural code.

The source NWB asset is intentionally stored outside Git under the operator data
root. The experiment excludes units marked `heldout`, preserves the dataset's
train/validation split, and records a count-preserving temporal shuffle control.

Example:

```powershell
$env:PYTHONPATH = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\python_packages"
$python = "$HOME\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$input = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\source\sub-Jenkins_ses-small_desc-train_behavior+ecephys.nwb"
$output = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\runs\sci096-dandi000140-probe-v1\result.json"
& $python experiments\challenge_cup_spike_coding\sci096_dandi_probe.py --input-nwb $input --output $output
```

Dependencies are isolated from Vibelution runtime dependencies:

- Python 3.12
- h5py 3.x
- numpy 2.x
- scikit-learn 1.x

The primary decision uses only the frozen `[-0.5 s, 0 s]` window relative to
movement onset. Other windows are reported as exploratory sensitivity evidence
and must not be used to retroactively select a favorable result.

## SCI-096 epoch discrimination

After human review of `stage1-sci-096-v2`, the follow-up experiment freezes two
epochs before execution:

- stationary preparatory epoch: `[-0.5 s, 0 s]`;
- movement-transition epoch: `[0 s, 0.25 s]`.

It tests whether the temporal-vs-rate decoding gain is larger in the transition
epoch, while retaining the capacity-matched decoder and count-preserving shuffle
control. All five preregistered gates must pass; otherwise the result remains a
branch or negative result rather than support for a universal coding claim.
The `v3` artifact supersedes the retained `v2` diagnostic because it uses a
class-stratified balanced-accuracy interaction bootstrap consistently with the
epoch-level gates.

```powershell
$env:PYTHONPATH = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\python_packages"
$python = "$HOME\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"
$input = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\source\sub-Jenkins_ses-small_desc-train_behavior+ecephys.nwb"
$output = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\runs\sci096-dandi000140-epoch-discrimination-v3\result.json"
& $python experiments\challenge_cup_spike_coding\sci096_epoch_discrimination.py --input-nwb $input --output $output
```
