# MCP Hub V1 completion scope

**Date:** 2026-10-04
**Status:** Approved for implementation

## Goal

Complete the V1 product behavior that can be built and verified in the cloud
workspace, while leaving the real iPhone, mobile-network, and Tailscale checks
as explicit manual acceptance steps. The product remains a single-user local
admin UI with a separate private Gateway endpoint.

## Scope

1. Preserve the existing T-001/T-002 lifecycle behavior and T-003 draft,
   validation, apply, and recovery behavior.
2. Complete T-004 through T-009 as vertical slices:
   - edit, disable, and delete services through the draft/apply flow;
   - distinguish Gateway status from per-downstream health and run a real MCP
     initialize plus tools/list probe;
   - provide a read-only, bounded, redacted Gateway log view;
   - enforce the selected file-service directory at the execution boundary,
     including traversal and symlink escape cases.
3. Add focused automated tests at the API, store, controller, and acceptance
   boundaries. Keep the existing acceptance contract as the source of truth;
   tests must not turn missing fixtures or missing devices into a pass.
4. Prepare T-010/T-011 run instructions and evidence fields, but do not claim
   real iPhone or mobile-network acceptance without an actual device result.

## Behavior decisions

- All service mutations first change the draft. Only “儲存並套用” writes the
  effective configuration and restarts the managed Gateway.
- A disabled service keeps its configuration but is excluded from the active
  Gateway configuration after apply. A deleted service is removed only from the
  Hub configuration; its process and data are not deleted by the Hub.
- A downstream is “可連線” only after both MCP initialize and tools/list have
  succeeded in the same check. Failures and timeouts are recorded per service,
  with an ISO timestamp; an old success cannot mask a disabled or failed state.
- Log viewing is read-only, bounded, and redacts credential-like values. Missing
  or unreadable logs are reported as errors rather than replaced with invented
  content.
- File access is restricted by the downstream execution configuration, not by a
  UI label or prompt. Tests use only isolated, self-created files.
- No V1 UI field accepts or stores credentials, tokens, headers, or secrets.

## Verification boundary

Cloud verification will run the repository tests and available isolated
acceptance checks. T-010/T-011 remain incomplete until a real iPhone uses the
private Gateway over mobile data and the required negative cases have recorded
evidence. The final handoff will state exactly which checks passed, failed, or
remain unverified.

## Out of scope

Public exposure, remote admin access, multi-user accounts, automatic wake-up,
credential management, and claims of end-to-end iPhone success without device
evidence.
