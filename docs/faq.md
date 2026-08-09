# Frequently asked questions

English | [简体中文](zh-CN/faq.md)

## What is RDE Core?

RDE Core is a local Python research core for bounded sequential experiment
selection over a finite candidate set. It combines deterministic built-in policies,
trusted workload adapters, local SQLite history, and versioned RunSpec, RunBundle,
verification, and recorded-observation replay contracts.

## What is RDE Core not?

It is not a hosted service, Web UI, GPU or cluster executor, continuous-learning
trainer, general plugin host, security sandbox, scientific-validity authority, or
the separately governed RDE Assurance product track.

## Is it formally RDE Core v1.0 now?

No. The public API is frozen for release-candidate preparation, but RDE Core remains
pre-release and is not yet release-ready. C6 documentation completion does not
establish later release readiness.

## Does it require a GPU?

No GPU is required, and current Core provides no GPU executor. This does not
constrain what a trusted user-supplied workload may use outside Core's executor
surface.

## Does it require a cloud service?

No mandatory cloud service is required. Experiment history uses local SQLite and
does not require a database server.

## Which Python versions are supported?

The frozen Core v1 contract supports CPython 3.12 (`>=3.12,<3.13`). Do not infer
support for another Python minor version from an incidental local run.

## Which RunSpec and RunBundle version should a new experiment use?

Use v3 when a new experiment needs the complete three-policy set. V1 and v2 remain
supported through the RDE 1.x compatibility line, but versions are exact: a RunSpec,
RunBundle, verifier, and replay function must match.

## How do `random`, `greedy_prior`, and `information_gain_table` differ?

| Policy | Current behavior |
| --- | --- |
| `random` | seeded selection without replacement from the remaining candidates in RunSpec order |
| `greedy_prior` | selects the highest user-declared static candidate utility, with RunSpec order breaking exact ties |
| `information_gain_table` | selects by deterministic expected information gain from a user-declared finite hypothesis/outcome/likelihood model and the current exact belief |

V1 supports `random`; v2 adds `greedy_prior`; v3 adds
`information_gain_table`.

## Does `information_gain_table` learn its likelihood model automatically?

No. The user explicitly declares the hypotheses, prior weights, outcome partition,
and complete candidate-by-hypothesis-by-outcome likelihood table. Core updates
exact belief weights from recorded observations; it does not learn or scientifically
validate the model.

## Does `greedy_prior` update from observations?

No. Its utility map is a static caller declaration. Observations do not update it.

## Does replay rerun my Python function or command?

No. Replay receives no callable, command builder, or command. It recomputes the Core
decision contract using the observations already recorded in a verified RunBundle.

## Is a RunBundle a container, virtual machine, or full environment snapshot?

No. It does not preserve an operating system, Python environment, executable,
dependency set, hardware device, network service, arbitrary file, or external data.

## Is a RunBundle hash a digital signature or encryption?

No. SHA-256 binds the bytes presented to the verifier for integrity checking. It
does not identify a signer, provide third-party attestation, encrypt content, or
provide confidentiality. Someone able to replace both bundle members can construct
a different self-consistent artifact.

## Does Verify PASS prove the scientific conclusion is correct?

No. Verification checks artifact structure, hashes, frozen version bindings, and
internal decision semantics. It does not prove that a workload, model, observation,
or scientific conclusion is true.

## Is PythonFunctionAdapter or CommandAdapter a security sandbox?

No. `PythonFunctionAdapter` runs trusted code in the current process.
`CommandAdapter` starts a trusted direct child with `shell=False`, but it is not a
sandbox or container and does not guarantee descendant process-tree cleanup.

## Can I dynamically load any policy plugin?

No. The current Core policy and replay factories are finite, static, and versioned.
An artifact cannot select an arbitrary module, class, callable, registry, entry
point, or URL.

## Will SQLite migration automatically downgrade a database?

No. Known legacy schemas migrate forward one atomic version step at a time to v6.
Downgrade and unknown future schemas are not supported.

## Does RDE Core depend on RDE Assurance?

No. They are independent product tracks. Core does not require Assurance to run.

## Does Core CI PASS equal RDE Assurance approval?

No. A passing Core CI run is neither Assurance approval nor proof that a user's
workload or scientific conclusion is correct.

## Is RDE Continual Learning included in Core?

No. Continual Learning is not part of the current RDE Core v1 surface.

## Can I use RDE Core with a real experiment?

The established adapters can connect trusted local Python or command workloads, but
Core remains pre-release. Users must validate their domain model, workload,
observations, operating procedures, and safety boundaries; Core does not perform
that scientific or operational validation for them.

## How should I report a bug?

Follow the [sanitized minimal reproduction guidance](troubleshooting.md#getting-useful-diagnostic-information).
Include public version and error information, but keep private databases, bundles,
paths, logs, and secrets out of the report.

## Can I put an API key in a RunSpec or RunBundle?

You should not. Do not put secret values in candidate parameters, RunSpec content,
observations, RunBundles, examples, or diagnostic logs. RDE Core is not a secret
manager, and environment-variable use alone does not make surrounding output safe.

## Can I install the current package from PyPI?

No supported PyPI installation is claimed or authorized for the current pre-release
Core. Use the authorized source-checkout installation described in the README; do
not substitute a similarly named package.

## Where can I learn more?

- [Troubleshooting](troubleshooting.md)
- [PythonFunctionAdapter guide](python-function-adapter.md)
- [CommandAdapter guide](command-adapter.md)
- [RunSpec guide](run-spec.md)
- [RunBundle guide](run-bundle.md)
- [Replay guide](replay.md)
