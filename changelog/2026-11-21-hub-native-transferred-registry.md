# Verify transferred vaults in native Agent sessions

Date: 2026-11-21

## Summary

An approved native Agent connection can verify its credential after the vault
registry moves to a Root-signed Owner-only starting checkpoint.

## Changes

- Include the authoritative signed starting checkpoint proof in transferred runtime sessions.
- Use that proof and the approval's exact registry sequence in the 1.3.2 native client.
- Preserve the earlier versioned downloads and their integrity hashes.

## Validation

- Verify the signed proof, native session response, versioned assets, and legacy host upgrade.
