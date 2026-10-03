Now I have all the context needed. Let me compile the review findings.

---

# T-002 Gateway-Control Deliverable Review

## Summary

The implementation is **largely correct in its core logic** (gateway-controller.js state machine, PID-file safety, hard deadline against CLI hang). The automated and manual evidence **does establish** the happy-path and two key negative scenarios (port squatter, corrupted PID). However, **three acceptance criteria have evidence gaps that are stronger than claimed**, and there are **untested failure modes** in the controller that could violate criteria 2 and 4.

---

## Findings by Criterion

### AC-1 — Single local entry opens usable interface, no terminal typing

| | |
|---|---|
| **Claim** | PASS (review-notes line 33) |
| **Actual evidence** | `start-hub.cmd` → `launch.js` spawns detached server, opens browser after fixed 1.5 s delay. HTTP 200 on `/` confirmed. |
| **Gap** | **Browser opens before server readiness is confirmed.** If port 3100 is occupied or server crashes, user gets “connection refused” in browser — not a usable interface. The evidence did not test the UI-button path (clicking “啟動 Gateway” from the page), only the `start-hub.cmd` entry point. |
| **Counterexample probe** | 1. Occupy port 3100 with another process, run `start-hub.cmd` → browser opens to `ERR_CONNECTION_REFUSED`.<br>2. Run `start-hub.cmd` when `@1mcp/agent` is not installed (fresh clone) → server crashes, browser still opens. |
| **Severity** | **Blocking** — “single entry opens a usable interface” is not met if the entry point can land the user on a dead page. |

---

### AC-2 — Start/stop/restart change real Gateway availability; failed start must not display Running

| | |
|---|---|
| **Claim** | PASS (review-notes line 45) |
| **Actual evidence** | Automated `check.py lifecycle` + `pair_calls()` shows tools callable after start/restart; `unavailable()` confirms stop works. Manual `POST /api/gateway/start` returns `state=running` with `Readiness (/health/ready): ready`. Port-occupied start returns `state=error`. |
| **Gap 1 — Readiness ≠ tool callability** | The controller deliberately ignores the CLI’s “Servers: X/Y ready” tally (comment lines 114–119) because it “printed 0/0 with both configured and actually serving.” It re-checks via `--status` → `/health/ready`. **But `/health/ready` only proves the Gateway HTTP server answers; it does not prove downstream MCP tools are reachable through the Gateway.** The `pair_calls` in the automated test calls tools **directly** (bypassing the Gateway), not via the Gateway’s `/mcp` endpoint. |
| **Gap 2 — `unknown` state not distinguished from `error` in UI** | `parseStatus` returns `unknown` for unrecognized exit codes or timeout. The UI (`app.js` `STATE_TEXT`) shows “Gateway 狀態未知” with grey styling (same as `stopped`), not the red error styling. A failed start that yields `unknown` would **not** look like an error to the user. |
| **Counterexample probe 1** | Start Gateway, then kill the downstream `everything-http` server (port 3051) while Gateway stays up. Call a tool **through the Gateway** (`POST /mcp` with `initialize` + `tools/call`). Observe whether the Gateway returns an error or hangs. If it returns an error, `/health/ready` is insufficient; if it hangs, the readiness contract is broken. |
| **Counterexample probe 2** | Simulate a CLI `--status` exit code 2 (not 0,3,4) with parseable PID but no readiness line. `parseStatus` → `unknown`. UI shows grey “Gateway 狀態未知”. User sees no red error. |
| **Severity** | **Blocking** (Gap 1) — criterion says “change real Gateway availability.” If readiness check doesn’t verify downstream reachability, the criterion is not established.<br>**Non-blocking** (Gap 2) — UI polish, but a failed start could silently show “未知” instead of “錯誤”. |

---

### AC-3 — Closing admin tab does not stop Gateway; reopening still works

| | |
|---|---|
| **Claim** | PASS (review-notes line 62) |
| **Evidence** | `check_002` does `page.close()` then `pair_calls()` — both services work. Independent: killing Hub process leaves Gateway supervisor + runtime alive, port 3050 still listening. |
| **Code support** | `launch.js` uses `detached: true`, `stdio: 'ignore'`, `child.unref()` — server is fully independent. No client-tracking logic exists. |
| **Gap** | None found. Architecture and evidence align. |
| **Severity** | — |

---

### AC-4 — Stale PID, unconfirmable identity, port conflict → clear error, never stop others

| | |
|---|---|
| **Claim** | PASS (review-notes line 67) |
| **Evidence** | Two scenarios tested:<br>1. **Port squatter**: external node on 3050 → start → `state=error` (36.5 s), squatter PID 42288 still alive, still owns port.<br>2. **Corrupted PID file**: `server.pid` = `99999` → status → `state=unknown` + CLI stderr; stop → `state=error` “程序仍在運作”; real runtime 44020 alive, 3050 listening.<br>Recovery works. |
| **Gap 1 — CLI succeeds but writes nothing parseable** | If `--status` exits 0 with empty stdout, `parseStatus` → `{ state: 'starting', pid: null, detail: '' }`. `start()` treats `starting` as not-`running` and returns error (line 121–122). **But the error message is generic** (“啟動指令已送出，但狀態未確認為運作中…”), not specific to “CLI gave unparseable output.” |
| **Gap 2 — Unrecognized exit code → `unknown` not handled as error in stop path** | `stop()` calls `status()` after `--stop`. If `status()` returns `unknown` (e.g., CLI exit code 2), line 139 `after.state !== 'stopped'` is true → returns error. **This is correct behavior**, but the error message (“停止指令已送出，但偵測到程序仍在運作…”) implies the process is still running, which may be false (could be CLI flake). |
| **Gap 3 — Timeout cleanup in `start()` may call `--stop` on a process the Hub doesn’t own** | Lines 103–109: on `start()` timeout, it runs `--stop` as cleanup. If the port squatter caused the hang, the 1mcp CLI **never created a valid PID file** (it was stuck in “runtime starting…”). `--stop` with no/invalid PID file is a no-op in the CLI — but this is an **assumption about CLI behavior not verified in evidence**. If the CLI’s `--stop` falls back to killing *something* on the port, it could hit the squatter. |
| **Counterexample probe 1** | Start Gateway. While `--background` is hung (port conflict simulated), send SIGKILL to the CLI child *before* the 30 s timeout, leaving a half-written `server.pid`. Then call `start()` again. Observe whether the cleanup `--stop` affects the squatter. |
| **Counterexample probe 2** | Corrupt `server.pid` to valid JSON but with a PID belonging to another user’s process (e.g., a different Node app). Call `stop()`. Verify the other user’s process is not terminated. |
| **Severity** | **Non-blocking** for Gaps 1–2 (behavior is safe, messages could be sharper).<br>**Blocking** for Gap 3 **if** the CLI’s `--stop` can act on a port without a valid PID file — this must be verified. |

---

### AC-5 — Admin page local-only; iPhone private remote path cannot open it

| | |
|---|---|
| **Claim** | PASS (review-notes line 94) |
| **Evidence** | Loopback: 200. Tailnet IP/hostname: connection refused. WSL node: curl 000. `Get-NetTCPConnection` shows only `127.0.0.1` listening. `config.js` hardcodes `hub.host = '127.0.0.1'`. |
| **Gap 1 — iPhone not directly tested** | Review-notes line 105 admits: “未從 iPhone 實測.” Inference from T-001 (tailscale serve only proxies `/mcp`) + WSL test. **Not direct evidence.** |
| **Gap 2 — Cross-user local access not tested** | Binding to `127.0.0.1` allows **any process on the same machine** (including other users’ processes) to reach the admin API. The task packet explicitly flags this. No evidence that this is mitigated or accepted. |
| **Gap 3 — No defense-in-depth** | No authentication, CSRF token, or origin check on the four admin routes. A malicious local page could `fetch('http://127.0.0.1:3100/api/gateway/stop', {method:'POST'})` and stop the Gateway. |
| **Counterexample probe 1** | On the test machine, run `runas /user:otheruser cmd /c "curl http://127.0.0.1:3100/api/gateway/stop -X POST"` → observe if Gateway stops. |
| **Counterexample probe 2** | Open a browser on the iPhone to `https://alvin.tail63d20f.ts.net:3100/` (or the Tailnet IP) → confirm connection refused. |
| **Severity** | **Blocking** (Gap 1) — criterion explicitly names “iPhone's private remote path”; inference ≠ evidence.<br>**Non-blocking** (Gaps 2–3) — local-only threat model accepted by design, but should be documented as a known limitation. |

---

## Additional Findings (Not Tied to a Single AC)

| # | File / Area | Issue | Counterexample Probe | Severity |
|---|---|---|---|---|
| A1 | `gateway-controller.js` `parseStatus` | Returns `unknown` for any exit code ∉ {0,3,4} or timeout. No test covers exit codes 1, 2, 5, etc. CLI could evolve new codes. | Run CLI with a wrapper that forces exit code 2; call `status()` → observe `unknown` propagates to UI as grey “未知”. | Non-blocking |
| A2 | `gateway-controller.js` `start()` line 105 | Cleanup `--stop` after timeout assumes CLI `--stop` is safe without valid PID file. Not verified. | See Gap 3 under AC-4. | Blocking (if CLI misbehaves) |
| A3 | `server.js` routes | No method validation beyond Fastify defaults; `GET /api/gateway/start` would 404 but `POST` with no body works. No content-type check. | `curl -X GET http://127.0.0.1:3100/api/gateway/start` → 404 (ok). `curl -X POST -H "Content-Type: application/json" -d '{}' …` → works (ok). But `curl -X POST -H "Content-Type: text/plain" …` → also works (Fastify parses as text). | Non-blocking |
| A4 | `config.js` `ensureGatewayConfigDir` | Runs on every `loadConfig()` (every server start). `mkdirSync(recursive:true)` + `writeFileSync` — no atomic write, no lock. Low risk (single-user local), but not idempotent under concurrent starts. | Start two Hub instances simultaneously (race) → observe `mcp.json` corruption or EEXIST. | Non-blocking |
| A5 | `launch.js` browser open | Fixed 1.5 s delay, no server readiness check. If server fails to bind, browser opens to dead page. | See AC-1 probe 1. | Blocking (part of AC-1) |
| A6 | `public/app.js` | `fetch` calls don’t check `response.ok`; a 500 from server would still try `response.json()` and likely throw, caught by `catch` → renders “無法連線到 MCP Hub 後端”. Misleading if server is up but controller returns 500. | Make `gateway.start()` throw an unhandled exception (e.g., corrupt config) → observe UI error message. | Non-blocking |

---

## Verdict per Criterion

| Criterion | Established by Evidence? | Notes |
|---|---|---|
| AC-1 | **No** | Entry point can open dead page; UI-button path untested. |
| AC-2 | **No** | Readiness check (`/health/ready`) ≠ downstream tool callability; `unknown` state not surfaced as error in UI. |
| AC-3 | **Yes** | Architecture + evidence align. |
| AC-4 | **Partially** | Two scenarios tested and pass; but cleanup `--stop` safety and unparseable CLI output not verified. |
| AC-5 | **No** | iPhone not tested; cross-user local access not addressed. |

---

## Minimum Additional Tests to Settle Open Questions

1. **Tool callability through Gateway** (AC-2): After `POST /api/gateway/start` returns `running`, call `POST /mcp` with `initialize` + `tools/call` on a configured downstream server. Verify success.
2. **iPhone remote access** (AC-5): Physical or simulated iPhone on same Tailnet → attempt `https://<tailnet-host>:3100/`.
3. **Cross-user local access** (AC-5): `runas /user:other` → `curl http://127.0.0.1:3100/api/gateway/stop -X POST`.
4. **CLI `--stop` behavior without PID file** (AC-4 Gap 3): In isolated env, remove `server.pid`, run `1mcp --config-dir … --stop`, observe whether it touches any process on port 3050.
5. **Server readiness before browser open** (AC-1): Modify `launch.js` to poll `/api/gateway/status` until `running` or timeout, then open browser. Test with port 3100 occupied.
6. **`unknown` state UI** (AC-2 Gap 2): Force CLI `--status` to exit code 2 → verify UI shows red error, not grey “未知”.

---

## Final Statement

**The deliverable does not meet all acceptance criteria on the recorded evidence alone.**  
AC-1, AC-2, and AC-5 have **blocking gaps** where the evidence is weaker than the PASS claim. AC-4 has a **potential blocking gap** (cleanup `--stop` safety) that hinges on unverified CLI behavior. AC-3 is the only criterion fully established.

The coordinator should require the additional probes above before accepting T-002.