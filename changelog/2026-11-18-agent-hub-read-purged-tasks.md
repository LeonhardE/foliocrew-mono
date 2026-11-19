# Read purged tasks without their retired envelopes

Date: 2026-11-18

## Summary

Trash can display the lifecycle record of an already purged task after the
encrypted task envelope has been retired.

## Changes

- Skip the task envelope read for terminal purged records, even when the recorded
  recovery deadline is still in the future.

## Validation

- Cover an already purged task whose envelope was retired and whose recorded
  deadline still lies in the future. Trash returns an unavailable envelope and
  a nonrestorable lifecycle record.
