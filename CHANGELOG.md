# Changelog

English | [Simplified Chinese](CHANGELOG.zh-CN.md)

Research Decision Engine Core (RDE Core) is pre-release.

- **Active private candidate:** `1.0.0rc5`
- **Public release:** `NONE`
- **Prior private candidate:** `1.0.0rc4`, which was superseded before publication
  when private-source commit references were removed from release-facing surfaces

The sanitized product repository remains private. No public repository release,
tag, or GitHub Release exists, and the package is not published to PyPI. This
changelog describes a private RC candidate, not a public release.

## [Unreleased]

### Added

- Added versioned RunSpec and RunBundle contracts: v1 supports `random`; v2
  supports `random` and `greedy_prior`; and v3 supports `random`, `greedy_prior`,
  and `information_gain_table`.
- Added `PythonFunctionAdapter` and `CommandAdapter` for trusted local workloads.
- Added SQLite-backed execution history with interruption and resume support.
- Added RunBundle export and read-only verification, plus version-matched replay
  from recorded observations.
- Added bilingual user documentation, Windows and Linux CI, and repository
  community issue and pull-request templates.

### Changed

- Aligned the public product display brand to Research Decision Engine Core, with
  RDE Core as the short name. The Python distribution remains
  `research-decision-engine`, the import package remains `research_decision_engine`,
  and the CLI remains `rde`.
- Froze the RC public API contract at exactly 112 manifest-listed symbols. An
  importable internal module or name is not public API merely because it can be
  imported.
- Advanced the latest SQLite schema to v6 while retaining supported one-version-at-
  a-time legacy migrations.
- Standardized the build backend on `uv_build==0.11.32`.
- Made the sanitized source-distribution boundary explicit for the future public
  product, excluding private development and private or raw audit, recovery,
  history, and Assurance evidence or material.

### Fixed

- Bound the frozen `DESIGN.md`, `PLAN.md`, and `SPEC.md` digests to their exact
  committed LF blob bytes. The document blobs, algorithm behavior, and schemas did
  not change; path-specific `.gitattributes` rules now preserve the LF checkout
  representation on Windows and Linux.
- Made each supported SQLite migration step atomic and resumable from the last
  committed schema after an interruption.
- Made Markdown checkout line endings portable across Windows and Linux.
- Improved the portability of Windows API typing when the package is checked and
  imported on Linux.
- Improved RunBundle identity and ancestry portability across the supported
  Windows and Linux workflows.
- Made compatibility checking producer-metadata-aware so callers compare the
  identity-bearing sections appropriate to their claim.
- Removed private-source commit identities from release-facing documentation,
  runtime metadata, tests, wheels, and source distributions. Public semantic role
  tokens are distinct non-Git identifiers; actual Git reads use one separately
  captured implementation commit.

### Security

- Established Apache-2.0 licensing and bilingual security policies.
- Documented a fail-closed privacy and secret gate that must pass before any future
  public release; that gate has not authorized public visibility or publication.
- Corrected the publication-security sequence to match GitHub's actual
  public-repository Private Vulnerability Reporting capability: explicit operator
  authorization precedes public visibility; Private Vulnerability Reporting is
  then enabled and verified immediately; public security, CI, and privacy gates
  pass before any tag, GitHub Prerelease, PyPI upload, or release announcement.
  Public security issues remain forbidden.
- Made RunBundle identity checking fail closed for unknown schemas, unsupported
  policy identities, malformed artifacts, and identity mismatches.
- Kept replay non-executing: it consumes recorded observations and does not invoke
  a Python callable, adapter, or command.
- Documented that adapters run at a trusted local process boundary and are not
  sandboxes for malicious code.

### Packaging

- Defined the normalized source distribution as exactly 121 members: 91 package
  members, 27 public-document members, and 3 build/licensing members. The RC5 notes
  are repository-tracked publication-gate records and are not sdist members.
- Kept `.gitignore`, `.gitattributes`, `.github/**` community-health files,
  `tests/**`, and private development and private or raw audit, recovery, history,
  and Assurance evidence or material out of the source distribution. The
  repository-only contribution guides do not enter the archive.
- Added verification for the wheel, source distribution, wheel rebuilt solely from
  the extracted source distribution, clean installation, and installed metadata.
- Established the prior private candidate by synchronizing the package version
  from `0.1.0` to `1.0.0rc1`.
- Advanced the active private candidate from `1.0.0rc1` to `1.0.0rc2` because
  public product brand and release metadata alignment changed the wheel and sdist
  bytes. No algorithm, storage, or schema behavior changed. Public release remains
  `NONE`, tag remains `NONE`, GitHub Release remains `NONE`, and PyPI status remains
  `NOT_PUBLISHED`.
- Advanced the active private candidate from `1.0.0rc2` to `1.0.0rc3` after RC2
  failed cross-platform release-contract validation. RC3 derives the three frozen
  design-document hashes from exact committed LF blob bytes. RC2 artifacts remain
  preserved as failed private evidence; there is no algorithm or schema change,
  tag, GitHub Release, or PyPI publication.
- Advanced the active private candidate from `1.0.0rc3` to `1.0.0rc4` because the
  corrected publication-security sequence changes packaged documentation and
  distribution bytes. RC3 was superseded before publication. There is no product
  runtime algorithm, schema, or public API symbol change; only
  `research_decision_engine.__version__.value` changes. Repository visibility
  remains `PRIVATE`, tag remains `NONE`, GitHub Release remains `NONE`, and PyPI
  remains `NOT_PUBLISHED`.
- Advanced the active private candidate from `1.0.0rc4` to `1.0.0rc5` because
  removing private-source commit references changes wheel and source-distribution
  bytes. Exact private provenance remains in external private evidence. Public API
  symbols, SQLite schema, RunSpec/RunBundle/replay contracts, and production
  decision algorithms are unchanged; only
  `research_decision_engine.__version__.value` changes. Repository visibility
  remains `PRIVATE`, tag remains `NONE`, GitHub Release remains `NONE`, and PyPI
  remains `NOT_PUBLISHED`.

### Documentation

- Added bilingual Quickstart material; Python-function and command-adapter guides;
  RunSpec, RunBundle, and replay guides; and Troubleshooting and FAQ pages.
- Added bilingual contribution guidance plus issue and pull-request templates.
- Added bilingual compatibility documentation and private, not-published RC
  candidate documentation. The retained RC3 notes now identify RC3 as a
  superseded, unpublished private candidate; the never-published RC1, failed RC2,
  and superseded RC3 evidence remain preserved in private history and immutable
  artifacts.
- Added bilingual `1.0.0rc5` notes for the private, not-published provenance-safe
  candidate.
- Added matching English and Simplified Chinese disclosures that the project is
  experimental and pre-release, was developed through a vibe-coding workflow with
  AI tools used throughout development, and has not yet been used in a real
  production environment.
