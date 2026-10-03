# Review: T-001 (code-review-audit, round 1)

## 1. Acceptance criteria → evidence mapping

| # | Acceptance criterion (from ticket) | Evidence file & location | Status |
|---|-----------------------------------|--------------------------|--------|
| AC-1 | 選定及記錄 Gateway、Open Minis、傳輸協定與兩個無憑證測試 MCP 的實際版本與相容性 | `versions.json` (all versions), `fixture.json` (protocol_versions, services), `handoff.json` (dependencies, verification step 23) | **CONFIRMED** for Gateway, test MCP, protocol versions, Tailscale, iOS; **[UNVERIFIED]** for Open Minis version (operator-reported 1.15 build 7, screenshot not attached) |
| AC-2 | 從 iPhone 關閉 Wi-Fi 的情境各呼叫兩個下游工具，與事先定義的結果核對；不得以桌面客戶端替代 | `handoff.json` step 19, `gateway-log-excerpt.txt` lines 24–29 (15:16:13–14Z), 32–36 (15:29:04–05Z), `versions.json` (iPhone tailnet IP 100.88.86.52) | **CONFIRMED** (both tools returned expected texts; source IP matches iPhone); **Note:** calls issued via `minis-mcp-cli` (python-httpx) in Minis on-device Linux env, not native in-app tool call |
| AC-3 | 授權裝置可呼叫，未授權來源拒絕；不開公開入口，不收集 Tailscale 憑證 | `handoff.json` steps 20–22, `gateway-log-excerpt.txt` line 21 (unauthorized 100.79.209.7 timeout, no gateway log after ACL), `versions.json` (tailscale_serve: tailnet only, path /mcp only) | **PARTIAL** — Authorized device ✅ CONFIRMED; Unauthorized rejected ✅ CONFIRMED; Only `/mcp` proxied ✅ CONFIRMED; No credential collection ✅ CONFIRMED; **No public entry: [UNVERIFIED]** — only config evidence (tailnet-only serve, CGNAT address), actual off-tailnet probe not executed (`handoff.json` step 24) |
| AC-4 | 只用受控、無副作用或安全測試資料的工具；保留可供後續重跑的無機密 fixture | `fixture.json` (isolated: true, secret-free gateway_url, deterministic get-sum calls), `versions.json` (test MCP is credential-free server-everything) | **CONFIRMED** |
| AC-5 | 不要求尚未建立的管理頁；管理頁隔離留在 T-002、T-010 驗證，不宣稱整個 US-12 已驗收 | `handoff-narrative.md` line 28, `ticket-T-001.md` line 40, `verify-ticket-final.json` (stdout: "MANUAL_CRITERIA_STILL_REQUIRED: this is not an iPhone or whole-ticket verdict") | **CONFIRMED** |

---

## 2. Findings

| finding_key | criterion_ref | description | blocking | concrete counterexample / evidence gap |
|-------------|---------------|-------------|----------|----------------------------------------|
| open-minis-version-unverified | AC-1 | Open Minis version 1.15 (build 7) is operator-reported; version screenshot not attached to evidence packet. | false | `handoff.json` step 23: `"actual": "Operator reported 1.15 (build 7); version screenshot not attached to evidence", "status": "UNVERIFIED"`; `versions.json` line 16: `"USER-REPORTED, version screenshot not yet attached [UNVERIFIED]"` |
| off-tailnet-probe-not-executed | AC-3 | No actual probe from a non-tailnet host to confirm the gateway is unreachable from the public internet. Only configuration evidence exists. | false | `handoff.json` step 24: `"actual": "Not executed; only configuration evidence (tailnet-only serve, CGNAT 100.x address) available", "status": "UNVERIFIED"` |
| minis-mcp-cli-not-native | AC-2 | iPhone calls exercised the gateway via `minis-mcp-cli` (python-httpx/0.27.2) in the Minis on-device Linux environment, not via Open Minis native in-app tool calling. | false | `handoff-narrative.md` line 32: "Open Minis 實際是透過其本機 Linux 環境的 `minis-mcp-cli`（python-httpx）呼叫，不是 App 原生工具呼叫"; `versions.json` line 17 |
| minis-dns-workaround-fragile | AC-2 | Minis environment uses carrier DNS which cannot resolve tailnet names; `/etc/hosts` entry added as workaround. This entry may be lost on Minis update/reset. | false | `handoff-narrative.md` line 33; `versions.json` line 18; rollback documented |
| http-downstream-session-staleness | (not a direct AC) | After HTTP downstream restart, 1MCP reuses stale session ID (`No valid session ID provided`) until Gateway restart. Known issue for T-005+. | false | `handoff-narrative.md` line 34 |

---

## 3. Recommended verdict

**PASS** — The core requirement is satisfied: the automated golden-path check (AT-001) passes; iPhone on mobile network (4G, Wi-Fi off) successfully calls both stdio and Streamable HTTP downstreams via the single Tailscale Serve entry point, returning the expected deterministic results; unauthorized tailnet source (100.79.209.7) is blocked by ACL with no gateway log entries; only `/mcp` is exposed (other paths return 404); the fixture is secret-free and retained; no admin UI is claimed. The two `[UNVERIFIED]` items (Open Minis version screenshot, off-tailnet probe) are evidence gaps but do not invalidate the demonstrated functionality. The documented limitations (Minis CLI vs native call, DNS workaround, HTTP session staleness) are explicitly acknowledged and scoped to future tickets.