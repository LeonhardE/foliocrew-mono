# Remove spent OAuth requests and credentials

Date: 2026-11-26

## Summary

Hub periodically removes expired connector requests and obsolete credential records
while preserving active connections and OAuth replay and disconnection behavior.

## Changes

- Use the Hub retention worker to remove expired consent attempts, unused codes and credentials.
- Keep only the protocol fields needed to detect replay against a live family or revoke the same native authorization. Release those references upon final expiry or account disconnect or replacement, as applicable.
- Reread candidates transactionally before deleting and keep unexpired entries belonging to other accounts.
- Expose only a fixed OAuth job status and validated public task and source counters in retention logs.

## Validation

- Exercised native and foreground OAuth authorization, rotation, stale-code replay, expiry, disconnection and replacement against the real protocol implementations.
- Ran the complete scheduled job on a due task with an encrypted report and an expired code. A second account kept its original task ciphertext and could still rotate its active connector credential.
- Checked two pages of physical removals and a retained active record in the loopback Firestore emulator.
- Checked that unexpected field names, private values, malformed counters and exception details cannot enter retention logs and that failures return a nonzero exit.
