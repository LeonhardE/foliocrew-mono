# Workspace admission

The Firebase Auth blocking functions check a verified Google identity with User Service. The
registration hook checks eligibility. The sign-in hook binds an outstanding invitation to the
Firebase UID and Google account through the User Service transaction, then issues a
`foliocrew_workspace: admitted-v1` session claim.

Run the tests locally after installing `requirements.txt`.

```sh
python -m unittest discover -s tests -v
```

The registered Docker image exercises the Python package and handlers in CI. Use the Firebase
source entry point for trigger registration.

See [the staging requirements](docs/staging.md) before registering an Identity Platform trigger.
