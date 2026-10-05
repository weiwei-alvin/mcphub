# MCP Hub V1 Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Complete the cloud-verifiable MCP Hub V1 behavior from T-004 through T-009 and prepare honest T-010/T-011 evidence instructions without claiming unperformed iPhone acceptance.

**Architecture:** Keep `ConfigStore` as the single draft/effective/last-good configuration boundary. Add a small MCP probe service for per-downstream health, a bounded read-only log reader, and thin Fastify routes that compose those services; the browser remains a client of those routes. File-scope enforcement stays at the configured downstream execution boundary, with isolated real-server acceptance fixtures rather than a prompt-only UI claim.

**Tech Stack:** Node.js CommonJS, Fastify 5, `@1mcp/agent` 0.38.2, `@modelcontextprotocol/sdk` 1.30.0, Node test runner, Python acceptance checker, Playwright when an isolated acceptance environment is available.

**Spec:** `docs/superpowers/specs/2026-10-04-v1-completion.md`

## Global Constraints

- Use the existing checkout at `/workspace/mcphub`; do not create a Git worktree.
- Keep the admin listener loopback-only (`127.0.0.1`); never expose it through the private Gateway endpoint.
- Keep V1 credential-free: reject and never persist secrets, headers, tokens, or passwords.
- Mutations edit draft state; only `儲存並套用` changes effective state and restarts the managed Gateway.
- Do not delete downstream programs or user data when deleting a Hub configuration entry.
- A health success requires MCP initialize and tools/list in the same check; stale success must not hide failure or disabled state.
- Log viewing is read-only, bounded, and redacted; missing or unreadable logs are explicit errors.
- Do not turn missing fixtures, Playwright, Tailscale, or an iPhone into a passing result.

## Review Focus

- A disabled service must remain visible in the draft, be rejected by the Gateway after apply, and not hide the health result behind an old success. Test in the service lifecycle and health tasks.
- A failed apply or recovery must leave the UI and effective file describing the same real state. Reuse and extend the existing recovery tests; do not bypass `ConfigStore.apply`.
- MCP probes must close spawned stdio processes and HTTP sessions on success, failure, and timeout. Test cleanup in the probe task.
- Log paths must not escape the configured log boundary, and sensitive-looking values must not be returned. Test traversal, missing files, and redaction in the log task.
- File fixtures must reject traversal and symlink escapes at the downstream boundary; a sentinel hash alone is not sufficient evidence. Add negative cases to the isolated acceptance instructions.

### Task 1: Complete service lifecycle mutations (T-004/T-005/T-006)

**Files:**
- Modify: `app/src/config-store.js`
- Modify: `app/src/server.js`
- Modify: `app/public/index.html`
- Modify: `app/public/app.js`
- Modify: `app/test/config-store.test.js`
- Create: `app/test/server.test.js`

**Interfaces:**
- `ConfigStore.disableService(name: string, disabled?: boolean): object`
- `ConfigStore.deleteService(name: string): void`
- `PATCH /api/services/:name` with `{ "disabled": boolean }` returns `{ service, services }` or a validation response.
- `DELETE /api/services/:name` returns `{ services }` and changes draft state only.
- `GET /api/services` continues to return draft rows, including `disabled: true` rows.

- [ ] **Step 1: Write failing store tests** for disabling a row while preserving its command/URL, deleting only the draft row, rejecting unknown names, preserving a disabled row across edit, and proving the effective file remains unchanged before apply.
- [ ] **Step 2: Run the focused store tests**

  Run: `npm test -- --test-name-pattern='disable|delete|disabled|draft'` from `app/`

  Expected: the new tests fail because the mutation methods do not yet exist.

- [ ] **Step 3: Implement the store mutations** in `app/src/config-store.js`. Validate the target name, write the draft atomically, preserve `disabled` through edits, and leave `mcp.json` untouched until `apply()`.
- [ ] **Step 4: Write failing Fastify route tests** using `fastify.inject()` and a fake Gateway controller. Cover PATCH/DELETE success, 404/400 errors, and an apply response that never reports a failed restart as HTTP success.
- [ ] **Step 5: Implement the routes** in `app/src/server.js`, injecting the store and Gateway controller for deterministic tests. Keep the existing 409 behavior for non-applied outcomes.
- [ ] **Step 6: Update the UI** so each row has `編輯`, `停用`/`啟用`, and `刪除`; disabled rows show `已停用`; mutations refresh the draft and require the existing apply confirmation before becoming effective. Use DOM text assignment, not HTML interpolation.
- [ ] **Step 7: Run the focused service tests**

  Run: `npm test -- --test-name-pattern='ConfigStore|service|gateway'` from `app/`

  Expected: all existing and new lifecycle tests pass.

### Task 2: Add real per-downstream MCP health checks (T-007)

**Files:**
- Modify: `app/package.json`
- Modify: `app/package-lock.json`
- Create: `app/src/mcp-probe.js`
- Create: `app/src/health-store.js`
- Modify: `app/src/server.js`
- Modify: `app/public/index.html`
- Modify: `app/public/app.js`
- Create: `app/test/mcp-probe.test.js`
- Create: `app/test/health-store.test.js`
- Modify: `app/test/server.test.js`

**Interfaces:**
- `probeService(service, { timeoutMs, ClientClass, transportFactory }): Promise<{ state: 'reachable'|'failed', checkedAt: string, message?: string, toolCount?: number }>`
- `HealthStore.check(name: string, service: object): Promise<HealthResult>`
- `HealthStore.get(name: string): HealthResult | { state: 'unchecked' }`
- `POST /api/services/:name/check` returns the service health result; unknown services return 404.

- [ ] **Step 1: Add the MCP SDK as a direct dependency** at the resolved installed version `1.30.0`, then run `npm install --package-lock-only` from `app/` and confirm `npm ci --ignore-scripts` can reproduce the lockfile without network bypasses.
- [ ] **Step 2: Write failing probe tests** with fake Client/transport objects. Assert initialize/connect and `listTools()` are both required, failures become `failed`, timeout is bounded, and `close()` runs for every outcome.
- [ ] **Step 3: Implement `mcp-probe.js`** using `StdioClientTransport` for `stdio` and `StreamableHTTPClientTransport` for `streamableHttp`. Pass no user-supplied environment secrets; use an explicit timeout wrapper and close the client/transport in `finally`.
- [ ] **Step 4: Write failing HealthStore tests** for unchecked, reachable, failed, timeout, disabled override, timestamp format, and per-service isolation.
- [ ] **Step 5: Implement `health-store.js`** as an in-memory per-server result map. A disabled service always reports `disabled`, even if it has an older reachable result; checking one service must not mutate another.
- [ ] **Step 6: Add the check route and UI**. Include health in service rows, render exact `可連線`, `連線失敗`, `已停用`, and `未檢查` states, render an ISO `time[datetime]`, and explain that health is a handshake/tools-list check rather than proof every tool works.
- [ ] **Step 7: Run health tests**

  Run: `npm test -- --test-name-pattern='probe|health|service check'` from `app/`

  Expected: all new probe, health, and route tests pass, including cleanup assertions.

### Task 3: Make Gateway logs available and safely viewable (T-008)

**Files:**
- Create: `app/src/log-reader.js`
- Modify: `app/src/config.js`
- Modify: `app/src/gateway-controller.js`
- Modify: `app/src/server.js`
- Modify: `app/public/index.html`
- Modify: `app/public/app.js`
- Create: `app/test/log-reader.test.js`
- Modify: `app/test/gateway-controller.test.js`
- Modify: `app/test/server.test.js`

**Interfaces:**
- `readLog({ filePath, boundary, maxBytes, readFile }): { state: 'available'|'missing'|'unreadable', text?: string, message?: string }`
- `GET /api/gateway/logs` returns a bounded redacted snapshot or an explicit missing/unreadable error.
- Gateway start receives the configured log path through the 1mcp `--log-file` option.

- [ ] **Step 1: Write failing log-reader tests** for bounded reads, missing/unreadable files, path escape/symlink rejection, and redaction of values following `token`, `password`, `authorization`, and `apiKey` markers. Assert the source file bytes are unchanged.
- [ ] **Step 2: Implement `log-reader.js`** with an explicit configured boundary, a maximum snapshot size, no writes/truncation, and deterministic redaction that does not print the original secret.
- [ ] **Step 3: Add `GATEWAY_LOG_PATH` configuration** with a safe default under the Gateway config directory, pass it to the managed 1mcp start command as `--log-file`, and update controller expectations without changing process ownership checks.
- [ ] **Step 4: Add the read-only route and UI** with button `查看日誌` and `role=log`; show missing/unreadable states instead of fabricated output.
- [ ] **Step 5: Run log/controller/server tests**

  Run: `npm test -- --test-name-pattern='log|GatewayController|gateway logs'` from `app/`

  Expected: the new log tests and all existing controller tests pass.

### Task 4: Verify real file-scope enforcement at the downstream boundary (T-009)

**Files:**
- Modify: `tests/acceptance/README.md`
- Modify: `tests/acceptance/check.py`
- Create: `tests/acceptance/fixtures/file-boundary.md`
- Create: `tests/acceptance/test_file_boundary_contract.py`
- Modify: `.harness/tickets/T-009.md`

**Interfaces:**
- The product configuration continues to pass an explicit allowed directory in the file MCP's stdio arguments; the Hub does not claim that a label or prompt is enforcement.
- The acceptance fixture defines `sandbox_root`, an allowed directory, an outside sentinel, and traversal/symlink probes without real personal data.

- [ ] **Step 1: Add contract tests** that reject a fixture without the isolation marker, reject a file server whose allowed path is outside the test root, and require explicit assertions for allowed success, denied traversal, denied symlink escape, and unchanged sentinel.
- [ ] **Step 2: Extend the acceptance checker** to issue real allowed and denied file-tool calls and check both the denial cause and sentinel hash; never convert missing Playwright/Gateway/fixture into PASS.
- [ ] **Step 3: Document the fixture setup and cleanup boundary** in `file-boundary.md` and `tests/acceptance/README.md`, including that the file MCP process—not UI copy—must enforce the allowed root.
- [ ] **Step 4: Run the contract tests**

  Run: `python -B -m unittest discover -s tests/acceptance -p 'test_*boundary.py' -v`

  Expected: contract tests pass without starting a product Gateway; real T-009 remains `UNVERIFIED` until the isolated fixture is supplied.

### Task 5: Run regression verification and prepare honest V1 handoff (T-010/T-011)

**Files:**
- Modify: `README.md`
- Modify: `TICKETS.md`
- Modify: `.harness/tickets/T-004.md` through `.harness/tickets/T-011.md`
- Modify: `tests/acceptance/README.md`
- Create: `docs/superpowers/verification/2026-10-04-v1-cloud-verification.md`

**Interfaces:**
- The verification note records commands, versions, exit codes, and limitations without secrets.
- Ticket status is updated only from actual evidence; T-010/T-011 cannot be marked complete without real phone evidence.

- [ ] **Step 1: Run the full Node test suite**

  Run: `npm test` from `app/`

  Expected: all existing and new tests pass.

- [ ] **Step 2: Run the acceptance checker self-tests and harness tests**

  Run: `python -B -m unittest discover -s tests/acceptance -p 'test_checker.py' -v` and `python -B -m unittest discover -s harness/runner -p 'test_*.py' -v`

  Expected: checker and runner tests pass; no product acceptance is inferred from these tests.

- [ ] **Step 3: Run a fresh app HTTP smoke test** with an isolated `GATEWAY_CONFIG_DIR` and temporary `HUB_PORT`, checking the UI, service API, health route, log route, and stopped Gateway state without touching user data.
- [ ] **Step 4: Run available T-003 through T-010 automated checks** only when explicit isolated fixtures and Playwright are present; record `PASS`, `FAIL`, or `UNVERIFIED` separately for each.
- [ ] **Step 5: Write the verification note and update ticket summaries** with the exact source hash, test outputs, cloud limitations, and the remaining iPhone/Tailscale manual checklist.
- [ ] **Step 6: Perform a final diff and status review**

  Run: `git diff --check`, `git status --short`, and the complete test commands above.

  Expected: no whitespace errors, no generated test data in tracked source, and no completion claim unsupported by a fresh command result.

## Self-review

- Spec coverage: service lifecycle is Task 1; health is Task 2; logs are Task 3; file-boundary enforcement/evidence is Task 4; regression and manual-device boundary are Task 5.
- Interfaces are consistent: server routes consume `ConfigStore`, `HealthStore`, and `readLog`; the UI uses the route names listed above; later verification consumes only recorded outputs.
- The plan does not introduce public networking, secrets, credential fields, or automatic iPhone claims.
- The highest-risk cases are explicitly pinned in Review Focus and assigned to their owning tasks.
