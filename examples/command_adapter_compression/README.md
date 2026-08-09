# Command Adapter Compression Tuning

This offline CPU example preserves the original RunSpec v1/RunBundle v1 `random`
compatibility fixture and the v2 comparison between exact policies `random` and
`greedy_prior`. It adds an opt-in v3 comparison across `random`, `greedy_prior`,
and `information_gain_table`. RunSpec v1 remains random-only; RunSpec v2 remains
limited to random and greedy-prior. Their canonical bytes, bundles, sidecars, and
recorded-observation replay contracts are unchanged.

The exact candidate space is `gzip|bz2|lzma` x levels `1|3|6|9` x
`single_stream|fixed_64_kib_members`, for 24 deterministic unique candidates. The
unchanged v1 fixture uses `random`, empty policy configuration, seed `1729`, and
an eight-experiment budget. The v2 comparison uses separate runs with the same
eight-experiment budget: v2 `random` uses seed `20260804`; v2 `greedy_prior` is
deterministic and forbids a seed.

The complete v2 prior-utility map is computed before workload execution only from
candidate parameters:

```text
codec_base: gzip=1000, bz2=2000, lzma=3000
level_component: level * 10
chunk_component: single_stream=1, fixed_64_kib_members=0
prior_utility: codec_base + level_component + chunk_component
```

For example, gzip level 1 fixed has utility `1010`, gzip level 1 single has
`1011`, and lzma level 9 single has `3091`. The map covers all 24 candidate IDs,
all values are finite and unique, and ties would resolve by exact RunSpec candidate
order through `runspec_candidate_order`. Utilities never update from observations
and are not inferred from corpus results or adapter output. They are a declared
truth-free heuristic, not a prediction of compression ratio; RDE cannot prove a
caller did not manually copy private truth into a declared utility map.

`corpus.txt` is project-authored structured workload text created for this repository. Its records describe the Core run, candidate, observation, persistence, and replay vocabulary and provide source-like repeated structure typical of logs and experiment manifests. It contains no downloaded or third-party corpus and no Assurance/recovery content. The project owns the authored bytes and commits them on the same redistribution basis as the surrounding example; no separate third-party attribution or license applies. Its identity is 145,258 bytes and SHA-256 `b23ded0b042d8ccf288f3b4a255becec15c78f039b360d6a4529af24815d65ca`; `.gitattributes` fixes LF checkout bytes. The workload verifies this identity before execution, compresses and decompresses the exact bytes, and rejects any round-trip difference. This is a real CPU workload because the standard-library codecs perform actual compression and decompression over the committed bytes rather than consulting a synthetic benchmark truth function. Gzip freezes `mtime=0`. The lzma levels use documented bounded dictionary sizes of 64 KiB, 256 KiB, 1 MiB, and 4 MiB respectively.

The objective is `compression_ratio = corpus_bytes / compressed_bytes`, maximized. Cost is a deterministic CPU-work proxy, not elapsed time: `(corpus_bytes * codec_weight * (level + 1) + member_count * 65536) / 1_000_000`, where codec weights are gzip 1, bz2 3, and lzma 5.

The command receives only the truth-free candidate fields. It emits exact canonical two-field normalized-observation JSON plus one LF on stdout and diagnostics on stderr. `CommandAdapter` executes with `shell=False`, no retry, bounded output, and a 30-second timeout. It handles and reaps the direct child; descendant process-tree cleanup is not guaranteed. RunSpec binds only the declared adapter ID/version, not executable bytes, builder source, the complete inherited environment, or the OS image.

For each v2 policy, the driver executes exactly four steps in a separate SQLite
run, closes all RDE and SQLite objects, reopens, verifies the exact RunSpec
fingerprint, and resumes through step eight. A mismatched fingerprint, policy,
candidate order, or greedy utility map fails before command execution. Each run
exports and verifies a RunBundle v2 and replays it into a new empty directory. It
reopens replay SQLite and compares candidate order, decisions, rationales,
observations, cumulative costs, empty belief lineage, terminal summary, and
section hashes. A command counter remains unchanged across both replays and
reconstruction, proving zero replay commands. Replay is recorded-observation
decision replay, not raw workload reproduction.

`PriorGreedyPolicy` selects the eligible candidate with the greatest fixed
declared utility, resolving ties by earliest RunSpec order. It receives only
completed candidate IDs; it does not inspect candidate parameters, objective
values, hidden truth, files, environment, or commands. It is distinct from the
legacy synthetic `GreedyPredictedPerformancePolicy`; no alias or semantic
conversion exists.

Run from either a source environment or an environment containing the installed wheel, from any working directory:

```powershell
python C:\path\to\examples\command_adapter_compression\run_example.py --output-dir C:\empty\caller-owned-output
python C:\path\to\examples\command_adapter_compression\run_v2_example.py --policy random --output-dir C:\empty\random-v2-output
python C:\path\to\examples\command_adapter_compression\run_v2_example.py --policy greedy_prior --output-dir C:\empty\greedy-v2-output
python C:\path\to\examples\command_adapter_compression\run_v3_example.py --policy random --output-dir C:\empty\random-v3-output
python C:\path\to\examples\command_adapter_compression\run_v3_example.py --policy greedy_prior --output-dir C:\empty\greedy-v3-output
python C:\path\to\examples\command_adapter_compression\run_v3_example.py --policy information_gain_table --output-dir C:\empty\information-gain-v3-output
```

The output directory must be absent or empty. All databases, bundles, replay
state, command counters, and `example-results.json` are written only there. The
reported random and greedy-prior observations are descriptive; the example does
not claim any policy is generally superior.

RunSpec v3 uses the same candidate order, corpus, workload command, cost proxy,
budget of eight, interruption after four steps, and random seed `20260804`. Its
finite information-gain model declares ordered hypotheses `gzip_dominant`,
`bz2_dominant`, `lzma_dominant`, equal integer priors, outcomes `low`, `medium`,
`high`, and compression-ratio thresholds 2.0 and 3.0. Every likelihood row totals
20. A candidate whose codec matches the hypothesis uses weights `(1, 5, 14)`;
all nonmatches use `(10, 7, 3)`. The complete 24 x 3 x 3 table is embedded in
the canonical RunSpec v3 and is never learned or changed.

The table is a project-authored heuristic demonstration prior. It is not fitted
from the example results, is not scientifically calibrated, and does not predict
which candidate will have the best objective. Replay reconstructs all three v3
policies only from recorded observations and executes zero adapters, callables,
or commands. Core v1 remains not release-ready.
