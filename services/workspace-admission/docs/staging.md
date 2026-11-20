# Workspace admission staging

Configure Firebase Authentication with Identity Platform in an isolated project. Point
`FOLIOCREW_INVITATION_USER_ORIGIN` at the matching User Service. Bind both functions to the same
dedicated runtime service account with `FOLIOCREW_INVITATION_FUNCTION_SERVICE_ACCOUNT` during
function discovery. Configure the User Service's `USER_INVITATION_AUTH_CALLER` with a one-entry
JSON map keyed by the callback account's numeric Google subject, with its service account email
as the value. Grant that account invocation permission on User Service only.

Pin `FOLIOCREW_INVITATION_CREATE_AUDIENCE` and `FOLIOCREW_INVITATION_SIGN_IN_AUDIENCE` to the
distinct values reported by Cloud Functions as `serviceConfig.uri`. Register the identical URIs
in Identity Platform. In staging, the deterministic regional aliases were reachable over HTTPS,
but Identity Platform accepted the canonical `*.a.run.app` origins from the function deployment.
Validate the signed audience and event type on both paths before relying on denial results.

Before registering the production triggers, verify these behaviors in staging.

- The Firebase SDK rejects unsigned or cross-project events. Google sign-in data identifies the
  actual Google provider and includes matching verified primary and provider email addresses.
- Uninvited Gmail accounts cannot register, and non-Google credentials cannot sign in. An invited
  account can sign in, refresh its token, and revisit the application with the same Firebase UID.
- Revocation, concurrent first sign-in, lost responses, and service outages preserve invitation
  state and return only a generic authentication error to the browser.
- Sign-in for the existing owner succeeds with the original UID. Config, Portfolio, and Hub
  enforce admission for direct user calls and preserve legitimate delegated operations.
- Both callbacks complete inside the Identity Platform deadline during cold starts and service
  contention. Exercise User Service after it has scaled to zero, including the first real Google
  login after idle time. Leave optional inbound Google OAuth credentials disabled.

Keep an export of the previous triggers. Restore that configuration before deleting either
callback during rollback. Keep the private-route rollout disabled until validation passes.
