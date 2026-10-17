# MCP Hub V1 cloud verification

**Date:** 2026-10-04
**Scope:** Current working tree after the V1 completion implementation pass

## Results

| Check | Result | Evidence |
| --- | --- | --- |
| App unit, route, controller, probe, health, log, and UI-contract tests | PASS | `cd app && npm test`; 66 tests passed |
| Acceptance checker self-tests | PASS | `python -B -m unittest discover -s tests/acceptance -p 'test_checker.py' -v`; 9 tests passed |
| File-boundary fixture contract tests | PASS | `python -B -m unittest discover -s tests/acceptance -p 'test_file_boundary*.py' -v`; 4 tests passed |
| Harness runner tests | PASS | `python -B -m unittest discover -s harness/runner -p 'test_*.py' -v`; 60 tests passed |
| App HTTP smoke | PASS | Temporary loopback app checked `/`, `/api/services`, `/api/gateway/status`, and missing-log response; 4 endpoints passed |
| Diff whitespace check | PASS | `git diff --check` |

## Implemented behavior

- Draft service rows now support edit, disable/enable, and delete without
  changing the effective configuration until apply.
- Per-service checks use MCP initialize plus tools/list, record timestamps, and
  distinguish unchecked, reachable, failed, and disabled states.
- Gateway logs have an explicit config-directory boundary, byte limit, symlink
  escape check, sensitive-value redaction, and a read-only UI panel.
- The T-009 checker requires an actual allowed root plus outside, traversal, and
  symlink-denial cases. It does not treat a UI label as enforcement.

## Not verified in this cloud pass

- No real isolated stdio/Streamable HTTP downstream fixture was provided, so
  AT-004 through AT-010 were not reported as product PASS.
- Playwright/Chromium was not installed for browser acceptance.
- T-009 was not run against a real file MCP process; only its fail-closed
  fixture contract was tested.
- No real Tailscale/private-network or iPhone/Open Minis session was available.
  T-010 and T-011 therefore remain TODO and must not be marked complete.
- The existing runtime harness state was not manually fabricated or rewritten;
  this note records code/test evidence only.

## Reproduction

Use the commands in the Results table from `/workspace/mcphub`. For product
acceptance, first create a separate directory with the marker and fixture
fields documented in [tests/acceptance/README.md](../../../tests/acceptance/README.md)
and [file-boundary.md](../../../tests/acceptance/fixtures/file-boundary.md),
then set `MCP_HUB_ACCEPTANCE_CONFIG` and
`MCP_HUB_ACCEPTANCE_ALLOW_MUTATION=1`. Missing or incomplete setup must remain
`UNVERIFIED`.
