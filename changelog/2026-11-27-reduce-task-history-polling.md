# Reduce repeat reads while waiting for a task report

Date: 2026-11-27

## Summary

A selected active run now checks for updates every five seconds while its progress dialog is visible. Closing the dialog switches the overview and results tabs to a thirty-second interval. Editing or browsing the trash pauses repeat reads.

## Changes

- Allow an outstanding history read to finish when moving between task views. The next check uses the interval for the visible view.
- Stop polling when the server reports a terminal state. Report receipts continue to update the original task's results.

## Validation

- Exercised view transitions, visibility, slow reads, task changes, and terminal reports. Ran the repository checks.
