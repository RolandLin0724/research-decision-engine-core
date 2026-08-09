# Contributing to RDE Core

English | [简体中文](CONTRIBUTING.zh-CN.md)

RDE Core is pre-release. The current canonical development repository is
private. These guidelines govern authorized collaborators now and contributors
to the future sanitized public product repository. No public v1.0 release
currently exists.

## Before contributing

- Read the [README](../README.md) (also available in
  [Simplified Chinese](../README.zh-CN.md)), the
  [Security Policy](../SECURITY.md) (also available in
  [Simplified Chinese](../SECURITY.zh-CN.md)), and the relevant user guide.
- Do not report a suspected security vulnerability in a public issue. Follow
  the private reporting instructions in the Security Policy.
- Do not include API keys, tokens, private data, or raw audit evidence in an
  issue, pull request, test, fixture, log, or example.
- Check whether the change belongs in RDE Core rather than RDE Continual
  Learning, RDE Assurance, or an external extension.
- Do not assume that an importable internal module is public API.

## Development environment

Use CPython 3.12 and `uv` 0.11.32. Create the locked development environment
with the synchronization command listed under Required local checks.

Do not document or rely on PyPI installation for this pre-release source tree.
Commands, documentation, tests, and reproductions must not contain local
absolute paths.

## Contribution types

Examples of suitable, narrowly scoped contributions include:

- bug fixes;
- portability fixes;
- documentation corrections;
- test improvements that preserve existing test nodes and contracts;
- narrowly scoped performance fixes supported by evidence;
- adapter improvements within the frozen public contract; and
- compatibility and migration fixes.

Open an issue and obtain design agreement before implementing any of the
following:

- new public API symbols;
- new RunSpec or RunBundle schema versions;
- new policies;
- SQLite schema changes;
- new adapters or executor models;
- removal or renaming of public symbols;
- changes to replay semantics; or
- changes to privacy, security, or packaging boundaries.

Submitting or discussing a proposal does not promise that it will be accepted
or implemented.

## Public compatibility boundaries

- The 112 public symbols are frozen for the release candidate (RC).
- Internal importability is not a compatibility promise.
- RunSpec and RunBundle v1, v2, and v3 remain supported.
- A schema must never be silently upgraded or downgraded.
- SQLite migrations must remain per-step atomic and resumable.
- Canonical fixtures must not be regenerated casually.
- Replay must use recorded observations and must not execute the original
  workload.
- Exact public errors, signatures, and data fields require compatibility
  review.

## Required local checks

Run the complete local gate from the repository root:

```powershell
uv lock --check
uv sync --locked
uv run ruff format --check .
uv run ruff check .
uv run mypy .
uv run pytest
uv run python -m research_decision_engine.core_release_check
uv build
```

Focused tests are useful during development, but they do not replace this full
gate.

## Tests and deterministic evidence

- Do not delete an opening test node.
- Do not use `skip` or `xfail` to hide a defect.
- Keep test collection deterministic.
- Provide relevant Windows and Linux portability evidence when behavior may
  differ by platform.
- Add or identify a test reproduction for the reported defect.
- Do not weaken fail-closed behavior.
- Keep the replay workload execution count at zero.

## Packaging boundary

- The build backend is `uv_build` 0.11.32.
- The approved normalized source distribution (sdist) contains 121 members:
  91 package members, 27 public-document members, and 3 build/licensing
  members.
- Private development material and private audit, recovery, and RDE Assurance
  evidence are excluded.
- `.github` community-health files are repository-only and are excluded from
  the sdist.

The 121-member count is the current release contract, not a promise for every
future version. Any change to it requires explicit release-contract review.

## Documentation

For a user-facing behavior or safety change, update the corresponding English
and Simplified Chinese documentation with the same meaning. Code identifiers,
schema IDs, and error classes are not translated.

## Privacy and security

Follow the root [Security Policy](../SECURITY.md) and its
[Simplified Chinese counterpart](../SECURITY.zh-CN.md). Exclude all of the
following from contributions and public discussion:

- API keys, tokens, and credentials;
- private email addresses;
- legal identities that were not intentionally made public;
- local absolute paths;
- real private databases;
- private RunBundles;
- unredacted CI logs; and
- raw review or recovery evidence.

## Pull requests

A pull request must:

- contain one coherent change and a clear rationale;
- link an issue when applicable;
- state the compatibility impact explicitly;
- list the exact tests run;
- explain the documentation impact and the privacy or security impact;
- avoid unrelated formatting churn;
- avoid committing generated build artifacts; and
- remain reviewable without a force-push requirement imposed by this guide.

## Licensing and provenance

Repository code is licensed under Apache-2.0. You must have the right to submit
all code, documentation, data, and fixtures in a contribution. Identify the
provenance of third-party material and confirm that its license is compatible.
No Contributor License Agreement (CLA) or Developer Certificate of Origin (DCO)
automation is currently configured. Submitting a contribution does not
authorize inclusion of proprietary or confidential material.

This guide does not provide legal advice.
