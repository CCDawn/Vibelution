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

## DANDI 000121 multi-session adapter

The SCI-096 v3 multi-session branch uses DANDI `000121` only after an
outcome-blind movement-onset protocol is frozen. The adapter:

- retains successful trials with a finite go cue, target acquisition, target,
  and recoverable hand-speed onset;
- applies a fourth-order 15 Hz Butterworth low-pass filter with zero-phase
  forward/backward filtering (effective eighth order), using fixed 250 ms
  kinematic context on both sides to avoid filter-edge onset artifacts;
- defines primary movement onset as the first post-go-cue sample reaching 20%
  of that trial's peak hand speed before first target acquisition;
- excludes anticipatory trials whose primary onset is less than 50 ms after
  the go cue and records the exclusion count;
- records 10% and 30% anchors as sensitivity evidence only;
- maps the target displacement from hand position at go cue into eight
  movement-direction octants and rejects sessions missing any octant;
- creates a deterministic per-octant 75/25 train/validation split and enforces
  at least 100 usable trials, 75 train trials, 25 validation trials, and two
  sorted units per session.

`sci096_dandi000121_adapter.py` only produces the existing decoder dataset
contract. It does not download DANDI assets, run neural decoding, or alter the
frozen stationary/transition windows and v3 decision gates.

### Frozen multi-session runner

`sci096_dandi000121_multisession.py` separates three gates:

1. the append-only qualification manifest selects exactly three frozen assets
   spanning Reggie and JenkinsC;
2. a download plan enforces the exact relative paths, byte sizes, SHA-256
   digests, and an 8.3 GB source ceiling;
3. formal decoding requires a separate human authorization artifact bound to
   the qualification manifest SHA-256.

Preparing a plan does not download data or authorize the experiment:

```powershell
$qualification = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\qualification\dandi000121\multisession_manifest_v2.json"
$sourceRoot = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\source\dandi000121"
$plan = "C:\Users\Administrator\Documents\Vibelution\data\experiments\sci096_spike_coding\qualification\dandi000121\download_plan_v1.json"
& $python experiments\challenge_cup_spike_coding\sci096_dandi000121_multisession.py plan --qualification-manifest $qualification --source-root $sourceRoot --output $plan
```

The formal `run` command additionally requires an append-only authorization
object with schema
`sci096.dandi000121.execution-authorization.v1`, the exact
`qualificationManifestSha256`, the frozen ordered `qualifiedSessionAssetIds`,
`formalExperimentAuthorized: true`, `authorizedBy`, and `authorizedAt`.
Authorization is checked before local asset access; all three downloaded NWB
files are then size- and SHA-256-verified before the adapter or decoder runs.
Unit rows with no spikes are deterministically excluded, and the resulting
non-empty count must match the qualification record before evaluation.

Each session retains the existing five SCI-096 v3 gates. Cross-subject support
requires at least two of three sessions to pass all five gates, at least one
supporting session from each monkey, a median interaction delta of at least
0.08, and a positive interaction in every session. This result remains limited
to the frozen assets, epochs, and offline controls.
