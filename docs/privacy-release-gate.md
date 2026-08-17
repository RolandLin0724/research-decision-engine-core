# Privacy and Secret Release Gate

English | [简体中文](zh-CN/privacy-release-gate.md)

This document records the mandatory gate policy for a public release. The sanitized
product repository became public only after every private-state preparation gate
passed and an operator explicitly authorized the visibility change. The `S0` through
`S11` sequence below then ran to completion for the `1.0.0rc5` release candidate.

The policy text is retained unchanged as the standing requirement for any future
release action. Only the current-status table at the end of this document states
present state.

## Frozen release model

| Field | Required value |
| --- | --- |
| Private canonical development/audit repository | `RolandLin0724/research-decision-engine` |
| Visibility | `PRIVATE_PERMANENT` |
| Public product repository | `SEPARATE_SANITIZED_REPOSITORY` |
| Public history | `ONE_NEW_ROOT_COMMIT_FROM_AN_EXACT_REVIEWED_TREE` |
| Private Git history | `NOT_COPIED` |
| Private refs/stashes/reflogs | `NOT_COPIED` |
| Raw review/recovery/audit evidence | `NOT_COPIED` |
| Public author | `RolandLin0724` |
| Public author email | GitHub noreply only |
| Legal name | `NOT_PUBLISHED` |

The private canonical repository remains private and preserves its complete audit
history. A future public product repository is a separate sanitized repository,
not a visibility change to the private repository.

## Mandatory private preparation and publication sequence

Before any future repository may become public, all of these requirements must be
independently verified:

- Record the exact private RC source commit and tree in private evidence.
- Export the exact reviewed Git tree without copying `.git`.
- Establish an explicit allowlist of files permitted in the public snapshot.
- Pass a full secret scan of the complete public snapshot.
- Pass a full absolute-path and identity scan of the complete public snapshot.
- Exclude all raw CI, review, recovery, and audit evidence.
- Confirm that all API keys, tokens, credentials, and authorization values are
  absent.
- Revoke or rotate every previously exposed credential before publication.
- Create the public commit with author `RolandLin0724` and a GitHub-provided
  noreply address.
- Confirm that the legal name and private email are absent.
- Include the Apache-2.0 `LICENSE`.
- Include `SECURITY.md`.
- Create the public snapshot as one new root commit from the exact reviewed tree.
- Keep the sanitized product repository private until every private-state
  preparation gate passes and an operator explicitly authorizes the visibility
  transition.
- Do not rewrite the private audit repository's Git history.
- Retain the private-to-public source and tree mapping only in private evidence.

After those private-state preparation gates pass, the publication sequence is
strict and fail closed:

1. `S0_PRIVATE_PREPARATION`: complete and verify every private-state preparation
   gate above.
2. `S1_OPERATOR_PUBLIC_VISIBILITY_AUTHORIZATION`: obtain explicit operator
   authorization for the private-to-public visibility transition.
3. `S2_VISIBILITY_PRIVATE_TO_PUBLIC`: change the sanitized product repository from
   private to public.
4. `S3_IMMEDIATELY_ENABLE_PRIVATE_VULNERABILITY_REPORTING`: immediately enable
   GitHub Private Vulnerability Reporting.
5. `S4_VERIFY_PRIVATE_VULNERABILITY_REPORTING_ACTIVE`: verify that Private
   Vulnerability Reporting is active.
6. `S5_ENABLE_OR_VERIFY_PUBLIC_SECRET_SCANNING_AND_PUSH_PROTECTION`: enable or
   verify public secret scanning and repository push protection.
7. `S6_ENABLE_OR_VERIFY_PUBLIC_CODE_SCANNING_WHEN_AVAILABLE`: enable or verify
   public code scanning when it is available.
8. `S7_ACTIVATE_OR_VERIFY_MAIN_BRANCH_RULES`: activate or verify the main-branch
   rules required by the public release gate.
9. `S8_RUN_PUBLIC_STATE_WINDOWS_AND_LINUX_CI`: rerun and pass Windows and Linux CI
   on the public commit, then rebuild the wheel and sdist and pass the installed API
   and documentation checks.
10. `S9_RUN_PUBLIC_REPOSITORY_LOG_ARTIFACT_AND_PRIVACY_AUDIT`: complete the public
    repository log, artifact, privacy, and security audit.
11. `S10_AUTHORIZE_TAG_AND_GITHUB_PRERELEASE`: only then may a separate operator
    authorization consider a tag or GitHub Prerelease.
12. `S11_OPTIONAL_SEPARATE_PYPI_RC_AUTHORIZATION`: any optional PyPI RC upload
    requires its own later authorization.

GitHub Private Vulnerability Reporting is enabled and its active state is verified.
From the moment visibility becomes public until its active state is verified, no
tag, GitHub Release, GitHub Prerelease, PyPI upload, or release announcement may
occur. Public issues must never be used to disclose a suspected vulnerability.

Copying private history, refs, stashes, reflogs, raw evidence, or recovery material
into the public repository is forbidden. Secret or credential values must never be
placed in release reports.

## Current status

| Item | Status |
| --- | --- |
| Current task | `POST_RELEASE_DOCUMENTATION_MAINTENANCE` |
| Full Git-history privacy audit | `COMPLETED_WITH_INCREMENTAL_EXTENSION` |
| Credential rotation/revocation | `COMPLETED_EXTERNALLY_OPERATOR_ATTESTED` |
| Sanitized product repository | `ESTABLISHED_PUBLIC` |
| Repository visibility | `PUBLIC` |
| Repository visibility change | `AUTHORIZED_AND_COMPLETED` |
| Private Vulnerability Reporting | `ENABLED_AND_VERIFIED` |
| Tag / GitHub Release / PyPI | `v1.0.0rc5 / PRERELEASE / PUBLISHED_1.0.0rc5` |

The credential response status is an external operator attestation. This task did
not perform or independently prove server-side revocation and did not inspect a
credential value. The current release-facing scan is deliberately narrower than a
full Git-history privacy audit. The established private product repository and its
audits do not authorize publication or a repository visibility change.
