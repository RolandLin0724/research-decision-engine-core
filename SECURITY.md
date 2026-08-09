# Security Policy

English | [简体中文](SECURITY.zh-CN.md)

## Supported versions

No public RDE Core release is currently supported.

The current private RC-preparation branch receives best-effort security fixes only
for its latest exact commit. Old private development commits are not supported
release lines. Neither package version `0.1.0` nor `1.0.0rc1` is a published,
supported release.

## Reporting a vulnerability

- Do not open a public issue for a suspected security vulnerability.
- Do not include secrets, credentials, private databases, or private RunBundles in
  any report.
- While this repository remains private, no external public reporting channel is
  active.
- The repository remains private until every private-state preparation gate passes.
  Changing it from private to public requires explicit operator authorization.
- GitHub Private Vulnerability Reporting is not claimed to be enabled while the
  repository is private. Immediately after an authorized public visibility change,
  it must be enabled and its active state verified. Once verified, use the
  repository's private **Report a vulnerability** flow.
- Private Vulnerability Reporting must be verified before any tag, GitHub Release,
  GitHub Prerelease, PyPI upload, or release announcement. During the interval
  between public visibility and verification, none of those actions may occur.
- After public visibility, Windows and Linux CI and the complete privacy and
  security audit must pass again before any release action.
- This policy does not publish a personal email address.
- No response-time or resolution SLA is promised during pre-release preparation.

Do not try to report a vulnerability through a public issue or through an assumed
GitHub direct-message feature.

## Information to include

Provide only sanitized information that is necessary to reproduce and assess the
problem:

- the affected public API or command;
- the package or repository version, or the exact commit;
- the Python version;
- the operating system;
- the security impact;
- a minimal sanitized reproduction;
- whether the problem affects a source checkout or an installed wheel;
- any relevant public exception class; and
- a suggested mitigation, when one is known.

Never include:

- API keys, tokens, credentials, or authorization headers;
- private database rows or private RunBundle contents;
- a personal email address;
- unredacted absolute paths; or
- raw CI logs that contain credentials.

## Security boundaries

- `PythonFunctionAdapter` executes user-provided Python in the current Python
  process.
- `CommandAdapter` executes a local child program.
- Neither adapter is a sandbox for malicious code. User workloads run with the
  permissions available to the current account and process.
- Replay uses recorded observations and does not re-execute Python callables or
  commands.
- RunBundle hashes detect supported forms of tampering. They do not provide
  encryption, confidentiality, or a digital signature.
- SQLite files and RunBundles may contain user-supplied metadata and observations.
- RDE Core is not a secret manager.
- RDE Core does not create RDE Assurance authority.
- A CI PASS does not prove scientific validity or the safety of user workloads.

These boundaries do not put a genuine escape, validation bypass, privilege
boundary bypass, or unintended execution path out of scope merely because an
adapter intentionally runs trusted local code.

## Coordinated disclosure

Keep vulnerability details private while triage and repair are underway.
Maintainers may request a sanitized reproduction. Public disclosure should wait
until a fix or mitigation is available. There is currently no bug-bounty program
and no guaranteed compensation program.

Public issues remain forbidden for vulnerability disclosure, including during the
short interval after an authorized public visibility change and before Private
Vulnerability Reporting is verified.

## Out of scope

The following are out of scope on their own:

- vulnerabilities solely in malicious user-supplied callable or command code;
- a compromised local operating system or Python interpreter;
- unsupported Python versions;
- claims based only on expected scientific performance; and
- secrets that a user voluntarily writes into a RunSpec, metadata, standard
  output, SQLite, or a RunBundle.

A report that demonstrates a genuine RDE Core boundary bypass remains in scope
even when user-provided code is involved.
