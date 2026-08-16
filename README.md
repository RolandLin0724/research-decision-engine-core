# Research Decision Engine Core

English | [简体中文](README.zh-CN.md)

## What RDE Core is

Research Decision Engine Core (RDE Core) is a local Python research core for bounded, sequential experiment
selection over a finite candidate set. It combines deterministic built-in policies,
trusted workload adapters, local SQLite history, and verifiable, replayable
RunBundles.

## Project status and development approach

Research Decision Engine Core is an experimental, pre-release project.

I built this project through a vibe-coding workflow. This means that I used AI
tools throughout the design, coding, testing, and documentation. I made the
final choices and reviewed the work, but mistakes and untested assumptions may
still remain.

RDE Core has not yet been used in a real production environment. It has not
been tested by a broad range of users or with a broad range of real workloads.
Most of the current evidence comes from automated tests, reproducible builds,
and CI checks. These checks are useful, but they do not replace long-term use
in real environments.

Please treat RDE Core as research software. Start with small, non-critical, and
reversible workloads. Review the inputs, outputs, and assumptions yourself. Do
not use it as the only basis for high-stakes decisions.

Clear bug reports, corrections, and practical feedback are welcome.

## What it is not

RDE Core is not a hosted service, a Web UI, a GPU or cluster execution system, a
continuous-learning trainer, or a general-purpose plugin host. It does not establish
that an experiment is scientifically valid, and it is not the separately governed
RDE Assurance product track.

## Current status

- **Pre-release:** RDE Core v1.0 has not been formally released. The active private
  candidate is `1.0.0rc5`; it is not published.
- **RC API freeze:** the public API is frozen for the release-candidate line and is
  covered by the RDE 1.x compatibility contract.
- **Prior private candidate:** `1.0.0rc4` was superseded before publication when
  private-source commit references were removed from release-facing surfaces. Its
  private, unpublished evidence is preserved externally.
- **Publication state:** the sanitized product repository is public. No public
  repository release, GitHub Prerelease, tag, GitHub Release, release
  announcement, or PyPI publication has occurred.
- **Private validation provenance:** exact private commit and workflow identities
  are retained only in external private evidence; the public package does not
  encode them.
- That Core CI result is not RDE Assurance approval and is not production-readiness
  approval.

## Requirements

- CPython 3.12
- `uv`
- local SQLite, accessed through Python's standard library; no database server is
  required
- no required cloud service
- no required GPU

## Installation from the current source repository

The permanent audit repository remains private. Authorized maintainers with an
existing private checkout can install the locked environment from its current
source branch:

```console
uv sync --locked
```

The sanitized product repository is `RolandLin0724/research-decision-engine-core`,
and it remains `PRIVATE`. No public clone command or PyPI installation is available
for this private candidate.

## Ten-minute Quickstart

After installation, create a new empty working directory under the repository root:

```console
mkdir quickstart
cd quickstart
```

Save the following as `quickstart.py`:

```python
from pathlib import Path

from research_decision_engine import (
    CandidateSpec,
    NormalizedObservation,
    PythonFunctionAdapter,
    RunSpecV3,
    export_run_bundle_v3,
    replay_run_bundle_v3,
    run_workload_trace_v3,
    verify_run_bundle_v3,
)
from research_decision_engine.storage import ExperimentStore

calls = {"count": 0}


def score(candidate: CandidateSpec) -> NormalizedObservation:
    calls["count"] += 1
    x = float(candidate.parameters["x"])
    return NormalizedObservation(
        objective_value=-(x - 2.0) ** 2,
        cost=0.25,
    )


candidates = [
    CandidateSpec("point-1", {"x": 1.0}),
    CandidateSpec("point-2", {"x": 2.0}),
    CandidateSpec("point-3", {"x": 3.0}),
]

adapter = PythonFunctionAdapter(
    score,
    adapter_id="quickstart.python",
    adapter_version="1",
)

run_spec = RunSpecV3(
    candidates=candidates,
    policy_id="random",
    policy_config={},
    policy_seed=17,
    experiment_count_budget=2,
    cost_budget=1.0,
    adapter_id="quickstart.python",
    adapter_version="1",
    objective_name="score",
    objective_direction="maximize",
)

database = Path("history.sqlite3")
with ExperimentStore(database) as store:
    store.init_schema()
    trace = run_workload_trace_v3(
        store,
        run_spec=run_spec,
        adapter=adapter,
    )
    history = store.list_workload_experiments(run_spec.fingerprint())

assert database.is_file()
assert len(history) == calls["count"] == len(trace.steps) == 2

bundle_directory = Path("run-bundle")
exported = export_run_bundle_v3(bundle_directory, trace=trace)
verified = verify_run_bundle_v3(bundle_directory)

assert exported.valid is True
assert verified.valid is True
assert verified.bundle_sha256 == exported.bundle_sha256

before_replay = calls["count"]
replay_directory = Path("replay")
replay_directory.mkdir()
assert not any(replay_directory.iterdir())

replayed = replay_run_bundle_v3(bundle_directory, replay_directory)

assert calls["count"] == before_replay
assert replayed.adapter_execution_count == 0
assert replayed.callable_execution_count == 0
assert replayed.command_execution_count == 0
assert replayed.equivalent is True
assert (replay_directory / "replay.sqlite3").is_file()

print(f"RunSpec: {run_spec.schema}")
print(f"Candidates executed: {verified.selected_candidate_ids}")
print(f"SQLite: {database}")
print(f"RunBundle verified: {verified.valid}")
print(f"Replay equivalent: {replayed.equivalent}")
print(f"Replay callable executions: {replayed.callable_execution_count}")
```

Run it from that directory:

```console
uv run --locked python quickstart.py
```

The final lines should confirm `RunBundle verified: True`, `Replay equivalent:
True`, and `Replay callable executions: 0`. The directory now contains
`history.sqlite3`, the two-file `run-bundle/`, and `replay/replay.sqlite3`.

The initial run invokes `score` twice. Replay then uses the recorded observations to
rebuild and check the decision history in fresh SQLite state; it does **not** invoke
`score` or any other workload callable again.

The example is intentionally single-use in its working directory. To run it again,
start in another new empty directory.

## Supported contract summary

| RunSpec / RunBundle | Supported policies |
| --- | --- |
| v1 | `random` |
| v2 | `random`, `greedy_prior` |
| v3 | `random`, `greedy_prior`, `information_gain_table` |

Use v3 for new experiments that need the complete three-policy set. V1 and v2 remain
supported by the RDE 1.x compatibility contract; Core does not silently upgrade or
downgrade their artifacts.

## What is persisted

The SQLite history stores completed workload records under the RunSpec fingerprint.
The exported RunBundle carries the complete versioned replay record, including:

- RunSpec identity
- candidate decisions
- observations
- rationales
- belief lineage where applicable
- per-step and cumulative cost
- terminal summary

## Trust boundary

- `PythonFunctionAdapter` executes a user-provided Python callable in the current
  Python process. The callable must be trusted.
- Core does not claim to sandbox malicious Python and provides no security isolation
  for this adapter.
- Replay consumes recorded observations and checks static decisions. It does not call
  the workload callable, invoke an adapter, or execute a command.
- RDE Core and RDE Assurance are independent product tracks. Core results create no
  Assurance authority or approval.

## License

RDE Core is licensed under the Apache License, Version 2.0.
See [LICENSE](LICENSE).

Public project identity: RolandLin0724.

## Security and privacy

- [Security policy and vulnerability reporting](SECURITY.md)
- [Privacy and secret release gate](docs/privacy-release-gate.md)

Completed current-tree and history privacy audits do not authorize direct public
conversion of the permanent private repository or publication of this candidate.
The sanitized product repository became public only after every private preparation
gate passed and an explicit operator authorized the visibility change. Private
Vulnerability Reporting is enabled and verified. The remaining public-release gate
stays open.

## Next reading

- [Changelog](CHANGELOG.md)
- [RDE Core v1 compatibility contract](CORE_V1_COMPATIBILITY.md)
- 1.0.0rc5 private candidate notes are retained only in the private repository
  and are intentionally outside the 121-member source distribution.
- [1.0.0rc3 historical notes (Superseded private candidate / Not published)](docs/release-notes/1.0.0rc3.md)
- [Testing RDE Core v1](TESTING.md)
- [PythonFunctionAdapter guide](docs/python-function-adapter.md)
- [CommandAdapter guide](docs/command-adapter.md)
- [RunSpec guide](docs/run-spec.md)
- [RunBundle guide](docs/run-bundle.md)
- [Replay guide](docs/replay.md)
- [Troubleshooting](docs/troubleshooting.md)
- [FAQ](docs/faq.md)
