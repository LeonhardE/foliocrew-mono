# Repository Instructions

## Commit conventions

- Use the contributing developer's Git author name and email configured for this repository.
  Automated commits made on their behalf must preserve that same identity.
- Credit Codex as a collaborator by adding `Co-authored-by: Codex <codex@openai.com>` to every commit message.
- Follow [Conventional Commits 1.0.0](https://www.conventionalcommits.org/en/v1.0.0/) for every commit message.
- Every commit must include a scope identifying its service or client, such as
  `feat(web): ...`, `fix(market): ...`, `feat(user): ...`, or `fix(config): ...`.
- Use the target name for new services and independently deployed workers, such as `research`,
  `research-worker`, or `notification`. Shared foundations use `shared`; repository-wide rules
  and tooling use `repo`.
- Infrastructure commits use the `infra` type and the affected target as their scope, such as
  `infra(user): ...`, `infra(market): ...`, or `infra(web): ...`.

## Change workflow

- Add one Markdown change record under `changelog/` for every material change, except changes
  confined to `local-docs/`.
- Creating, updating, or deleting local-only documentation in `local-docs/` does not require a
  changelog entry. For a mixed change, record only the material changes outside `local-docs/`.
- Follow the naming and content convention in `changelog/README.md`.
- Run `npm run check` from the repository root before committing.

## Browser flow acceptance

- Test the user’s actual workflow through the UI. Open the browser Network panel before the
  first action, enable log preservation, and capture the whole flow with all request types
  visible. Watch the UI during intermediate states as well as at completion.
- A successful flow requires a clean UI, zero failed requests in the flow, and the expected
  outcome on the original item. A transient error banner, a cancelled or rejected request,
  or a retry that eventually succeeds still requires investigation. Keep the run marked failed
  until the cause is fixed and a fresh run passes. Record deliberately tested error paths separately.
- Record request counts and timings per action, check repeated reads and polling intervals,
  and verify that requests settle when the work is complete. Explain repeats using the flow’s
  actual needs. Include the counts, delays, and outcome in the acceptance record. Redact
  credentials and private data from evidence.
- For background work, also verify the exact trigger and a durable result on the original task
  after closing the requested pages, including whether a user approval was needed. If network
  capture or an end-to-end check is missing, report that part as unverified.

## Branch tracking

- Create feature branches without tracking `main` or `origin/main`; use `--no-track` when
  branching from `origin/main` and verify the upstream immediately afterward.
- On first publication, explicitly push the feature branch with `-u` to its same-named remote
  branch. Only the local `main` branch should track `origin/main`.

## Documentation

- Keep each component's README as an entry point and put maintained topic references under
  `docs/`. Update or consolidate an existing guide before adding a new topic file.
- Keep implementation journals, ticket progress and experimental evidence in ignored `local-docs/`;
  use `changelog/` for tracked material-change records.
- Preserve required license notices and supported compatibility specifications. Update local
  links and heading anchors whenever documents move or merge.

## Pull request scope

- Each new implementation PR must target exactly one backend service or the frontend
  (`apps/web`). Do not combine multiple services or backend and frontend changes in one PR.
- Include the selected target's tests, dependency files, Docker configuration, service-specific
  deployment configuration, documentation, and required changelog in that PR as needed.
- Changes to shared libraries or contracts, repository-wide infrastructure, or workflow rules
  belong in separate foundation-only PRs. Do not bundle changes to their consuming services or
  frontend into those PRs.
- Deliver cross-service work through ordered, backward-compatible PRs: introduce shared
  prerequisites or producer APIs first, then update each consumer in its own PR. Each PR must
  be independently verifiable and safe to merge and deploy.
- Infrastructure provisioning follows the same single-target rule at both commit and PR
  level. Put each service or client's cloud resource configuration in its own infrastructure
  commit and PR; do not combine, for example, User and Market provisioning.
- Shared infrastructure modules belong in a separate `infra(shared)` foundation PR;
  repository-wide state/bootstrap and execution tooling use `infra(repo)`. Add or migrate each
  consuming service in its own subsequent infrastructure PR. A shared scope must not be used
  to bundle multiple services' resource instances.
