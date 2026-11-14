# Settle native account failures and restrict page framing

Date: 2026-11-14

## Summary

Native account pending errors and malformed replies now finish instead of leaving the original
request waiting after its timeout was removed. Web responses also apply a minimal framing and MIME
policy while retaining existing login, Worker and theme behavior.

## Changes

- Validate pending success values before optional fields and settle normal errors through the
  existing fixed failure path. Remove the original timeout together with settlement; malformed
  non-JSON or oversized replies close and settle the channel. Keep exact branded source/origin/
  nonce attachment and account-link-only commands unchanged.
- Set all routes to `frame-ancestors 'none'; object-src 'none'; base-uri 'self'`, X-Frame-Options
  DENY and nosniff. This is framing/MIME hardening, not a full XSS script policy. No default/script/
  connection/Worker/popup restriction is added. Agent handoff retains no-referrer; other routes use
  strict-origin-when-cross-origin for future browser-key origin restrictions.

## Validation

- The actual production bridge and real MessageChannels cover failed/null/malformed pending replies,
  explicit retry, cleanup timers, cyclic/BigInt/oversized replies, wrong request IDs, late replies,
  abort, close and successful approval; original source/origin/nonce rejection tests remain.
- Actual Next header configuration and unchanged inline theme execution regressions verify the
  minimal policy, route-wide behavior and Agent referrer override. Production HTTP header probes,
  existing login/Worker/bridge regressions and the complete root gate verify compatible behavior.
- No real account or current unlocked browser session is used for these checks. Live Google popup
  and Passkey acceptance remain subject to the original explicit browser/user flow.
