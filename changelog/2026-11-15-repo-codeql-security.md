# Add isolated semantic code security analysis

Date: 2026-11-15

## Summary

Add CodeQL analysis for the monorepo's JavaScript/TypeScript and Python source to complement
the existing secret scanner, lint rules and behavioral tests.

## Changes

- Run separate language jobs for pull requests and trusted-main pushes, using fixed official
  checkout and CodeQL action commits and the extended security query suite.
- Use build-free analysis without installing application dependencies or accessing GCP, workload
  identities, deployment secrets or production APIs. Keep the existing required aggregate and
  branch protection rules unchanged.
- Limit job permissions to source read and code-scanning result publication; do not upload analysis
  databases. Bound parallelism, cancel superseded scans and impose a job timeout.
- Keep scanning separate from image deployment filters and do not add a scheduled trigger.

## Validation

- Verified the fixed CodeQL action commit and supported inputs against GitHub's official source.
- Existing CI selection continues to require all target checks for workflow changes; current
  production image triggers do not match the new workflow path.
- The actual language analyses and result processing must complete before claiming scan coverage
  or triaging their findings; an unavailable alerts API is not evidence of zero vulnerabilities.
