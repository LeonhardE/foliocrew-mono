# Foliocrew MCP resource name

Date: 2026-11-22

## Summary

MCP clients can identify the native Agent connection as Foliocrew during OAuth discovery.

## Changes

- Advertise `Foliocrew` as the public resource name for native MCP v3 on both serving origins.

## Validation

- Check the advertised name, resource, and issuer through both the direct and signed branded routes.
