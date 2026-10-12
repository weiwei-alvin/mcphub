# 驗收作業單 — MCP HUB T-005～T-009

> 交付對象：Antigravity（獨立審查）
> 產出日期：2026-10-12
> 專案：MCP HUB（產品 repo：`C:\Users\m8508\mcphub`；harness/規劃：`D:\AI-Lab\MCP HUB`）
> 目的：由第三方獨立核對 T-005～T-009 的修補正確性與驗收證據，並確認 T-010/T-011 的阻塞判定是否成立。

---

## 0. 摘要

| 工單 | 狀態 | verify-ticket receipt | review |
|---|---|---|---|
| T-005 停用 MCP 並阻止呼叫 | COMPLETE | `verifications/46659083bdf94d7cabe95dd713481aff.json` | `reviews/80c72e5d0db2437c99c6af269ee84ee5.json` |
| T-006 刪除 MCP 設定並阻止呼叫 | COMPLETE | `verifications/8ec7f44f631a43008d8ac46702db1197.json` | `reviews/30853ef4ee244f66a8f45882c3e5d81e.json` |
| T-007 顯示下游檢查結果並測試連線 | COMPLETE | `verifications/397d006db7804feebf537b3622e350fe.json` | `reviews/41a32d2280a64bc7b177040cd68de583.json` |
| T-008 唯讀查看 Gateway 日誌 | COMPLETE | `verifications/6fc576d23cae496db6305382f994d034.json` | `reviews/43cdeb4838f445508842c730aac3bfc1.json` |
| T-009 限定檔案 MCP 操作範圍 | COMPLETE | `verifications/4c131bcbf2e54b968f2b512e0e0a7f38.json` | `reviews/9c9aa89f2f9a4afda0de4824d705fe67.json` |
| T-010 iPhone／離線恢復 | **PAUSED（阻塞）** | — | reason=`REVIEW_USER_DECISION_REQUIRED`, decision_ref=`DEC-001` |
| T-011 V1 整合驗收 | **阻塞（依賴 T-010）** | — | — |

所有 receipt 在 `D:\AI-Lab\MCP HUB\.harness\verifications\`，所有 review 在 `D:\AI-Lab\MCP HUB\.harness\reviews\`。
Harness 狀態：`D:\AI-Lab\MCP HUB\.harness\state.json`（`project_status=PAUSED`）。

---

## 1. 審查者應獨立確認的事項（Checklist）

- [ ] 逐張打開對應 receipt：`all_passed=true`，且 AT-001…AT-00N 每個 `status=PASSED`、`returncode=0`，`source_hash` 一致。
- [ ] 逐張打開對應 review：`verdict=PASS`，criteria 覆蓋所有 AT step（critical+PASS），人工/負向 criteria 有 `source` 與 `limitations`。
- [ ] 產品 repo `C:\Users\m8508\mcphub\app`：`npm test` 應 76/76 PASS。
- [ ] 對 @1mcp 的 patch 僅限 `patches/@1mcp+agent+0.38.2.patch` 記載的三檔，且 `git apply --check` 可套用於 pristine `@1mcp/agent@0.38.2`。
- [ ] 確認未 commit/push、未改 harness state 以外的人工內容（state 由 runner 寫入）。
- [ ] 確認 T-010 阻塞判定：無 iPhone 實機即可判定不可完成；AT-010 需非 loopback 的 tailnet 端點，本機 Tailscale 為 `NoState`（未登入）。

---

## 2. 環境與重現前提

- 驗收隔離目錄：`D:\AI-Lab\MCP-HUB-acceptance\followup-20261011-t005-formal-09\`
  - `fixture.json`（isolated=true、sandbox_root、services=2、gateway_log/log_marker、outside_sentinel、file_allowed/file_denied）
  - `hub-t005.cjs`（Hub 啟動：UI 3230、Gateway 3213、configDir=gateway-config、logFile=gateway-config/gateway.log）
  - `servers\baseline-http.mjs`（3214，server-everything streamableHttp）
  - `servers\replacement-http.mjs`（3215，T-004 replacement）
  - `servers\file-mcp.mjs`（T-009 隔離 file MCP，限縮 allowed dir）
- 產品程式（實際被載入）：`C:\Users\m8508\mcphub\app\src\server.js`（`hub-t005.cjs` 以 `require` 指向此路徑）。
- 依賴：Node.js 24.x（Windows）、`@1mcp/agent 0.38.2`、fastify 5.12.5、Docker（僅 T-003 前置曾用；本輪 stdio fixture 已改 node）。

### 重現步驟（單張工單）
```powershell
# 1) 準備環境（示意；實際已於 formal-09 完成）
#    起下游：node servers\baseline-http.mjs / replacement-http.mjs
#    起 Hub：node hub-t005.cjs
#    reset mcp.json 為 fixture 兩服務（+ T-009 的 fs 服務），再啟動 Gateway
# 2) 設定 fixture 與授權
$env:MCP_HUB_ACCEPTANCE_CONFIG = "D:/AI-Lab/MCP-HUB-acceptance/followup-20261011-t005-formal-09/fixture.json"
$env:MCP_HUB_ACCEPTANCE_ALLOW_MUTATION = "1"
# 3) 正式驗收（會重跑該工單與其前置的所有 AT）
python -B harness/runner/runner.py verify-ticket --ticket T-005 --trust-commands --timeout 500
# 4) 標記 ready 後送 review（review/handoff payload 見 §4 範本說明）
python -B harness/runner/runner.py mark-ticket-ready-for-review --ticket T-005
python -B harness/runner/runner.py review-verdict --ticket T-005 --verdict PASS --review <review.json> --handoff <handoff.json>
```
（`workdir` 皆為 `D:\AI-Lab\MCP HUB`。）

---

## 3. 各工單：問題、修補、證據

### T-005 停用 MCP 並阻止呼叫
**兩層根因**
1. `@1mcp` supervisor 在 worker 被殺後自動 respawn，與 Hub 的 `--stop` 競態 → `Cannot verify supervisor or worker process identity`，apply 停用永遠寫不進 `mcp.json`。
2. 停用後 `@1mcp` 把該 server 工具整個移除 → tools/call 回 `Unknown tool`，而驗收要求回含 `disabled` 的明確拒絕。

**修補（產品，`C:\Users\m8508\mcphub\app`）**
- `src/gateway-controller.js`：新增 identity-race 辨識（`isIdentityRace`、4 個 marker）、`_waitForIdentitySettle()` 輪詢、`stop()/start()` 遇 race 先 settle 再重試一次；`parseStatus` 回傳 `identityRace`。
- `test/gateway-controller.test.js`：+6 測試。

**修補（第三方，patch）**
- `patches/@1mcp+agent+0.38.2.patch` 第三 hunk：`toolRequestHandlers.js` 的 Unknown-tool 分支，遇 `disabled` server 回 `isError:true` + `Server is disabled: …`。

**證據**：receipt AT-001..AT-005 全 PASS；`npm test` 76/76；formal-09 手動停用後 tools/call 回 `{"isError":true,…"Server is disabled: …"}`。

### T-006 刪除 MCP 設定並阻止呼叫
**根因**
1. UI `mutateService` 對 DELETE 也送 `Content-Type: application/json` 但無 body → Fastify 400 `FST_ERR_CTP_EMPTY_JSON_BODY` → 刪除鈕完全無效。
2. 已刪除 server 的 call 只回 `Error calling tool`，不含 `disabled`。

**修補**
- `public/app.js`：`mutateService` 僅在有 body 時送 `Content-Type`。
- patch 擴充：`toolRequestHandlers.js` 對「prefix 對不到已設定 server」也回含 `disabled` 的明確拒絕。

**證據**：receipt AT-001..AT-006 全 PASS；Playwright probe 刪除後 row 由 1→0、`hub-draft.json` 移除該服務。

### T-007 顯示下游檢查結果並主動測試連線
**根因**：列內同時有「啟用欄 `已停用`」與「健康欄 `已停用`」→ Playwright strict-mode violation（2 個符合）。
**修補**：`public/app.js` 啟用欄文字改 `停用中/啟用中`（健康欄維持契約要求的 `可連線/已停用/連線失敗/未檢查`）。
**證據**：receipt AT-001..AT-007 全 PASS（check_007 驗 可連線+時間戳、停用後 已停用）。

### T-008 唯讀查看 Gateway 日誌
**根因**：`hub-t005.cjs` 把 logFile 設在 `logs/`（Hub 讀取邊界=configDir 之外）→ `/api/gateway/logs` 永遠 `unreadable`；產品預設其實是 `configDir/gateway.log`。
**修補**：`hub-t005.cjs` logFile 移入 `gateway-config/gateway.log`；`fixture.json` 加 `gateway_log` + `log_marker`（`ConfigChangeHandler initialized`）。
**證據**：receipt AT-001..AT-008 全 PASS；`/api/gateway/logs` state=available 且含 marker；檢視後檔首前綴不變。
**備註（供審查判斷）**：此為「測試環境設定偏離產品預設」的修正；產品 `src/log-reader.js` 未改。若審查認為產品應放寬邊界至 sandbox root，請提出，屬設計取捨。

### T-009 限定檔案 MCP 的實際操作範圍
**根因**：環境無可用 file MCP（`@modelcontextprotocol/server-filesystem` 不存在）。
**修補（測試基礎設施）**：新增 `servers/file-mcp.mjs`（stdio；只讀 allowed dir；`path.resolve` 正規化後範圍外回 `Access denied:`）；`fixture.json` 加 `outside_sentinel`、`file_allowed`、`file_denied`。
**證據**：receipt AT-001..AT-009 全 PASS；手動 probe：allowed→`allowed-content-ok`、denied→`isError:true "Access denied: … outside the allowed directory"`。
**備註**：產品側未改（Hub 以既有 command/args 傳 allowed dir）；symlink 類繞過未逐一證明（review 已列 limitations）。

---

## 4. 變更檔案清單

### 產品 repo `C:\Users\m8508\mcphub`（`git status`）
```
 M app/public/app.js            (T-006 Content-Type、T-007 標籤)
 M app/src/gateway-controller.js (T-005 identity race)
 M app/test/gateway-controller.test.js (+6 測試)
 M .harness/state.json          (runner 寫入)
```
（`app/public/index.html`、`app/src/config-store.js`、`app/src/mcp-probe.js`、`app/test/*.js` 亦有標記變更，屬本 session 前的既有未提交基線，非本輪新增；請以本作業單 §3 描述為準逐檔核對 diff。）

### harness repo `D:\AI-Lab\MCP HUB`
```
 M app/patches/@1mcp+agent+0.38.2.patch   (T-005/T-006 toolRequestHandlers hunk)
 M .harness/state.json
?? .harness/reviews/…                     (T-005..T-009 review 工件)
?? .harness/verifications/…               (PASS receipts)
```
> 註：`C:\Users\m8508\mcphub\app\node_modules\@1mcp\…\toolRequestHandlers.js` 與 `D:\AI-Lab\MCP HUB\app\node_modules\…` 兩份 node_modules 皆有同一 patch（驗收實際載入 C: 那份）。

### 驗收環境 artifact
```
D:\AI-Lab\MCP-HUB-acceptance\followup-20261011-t005-formal-09\
  fixture.json, hub-t005.cjs, servers\{baseline-http.mjs,replacement-http.mjs,file-mcp.mjs}
  gateway-config\{mcp.json,hub-draft.json,gateway.log}
  logs\ , verification\ (T-005 手動截圖)
```

---

## 5. 已知限制與阻塞

1. **T-010 阻塞**：工單明訂「缺手機操作證據則本張不可完成」；且 AT-010 需 `private_gateway_url`（`remote_only` 要求 tailnet 位址），本機 Tailscale 狀態 `NoState`（未登入，介面僅 169.254/16），無可達私人端點。
2. **T-011 阻塞**：依賴 T-010。
3. **驗收環境 flakiness**：`verify-ticket` 連續執行多個 AT 時，若 stdio 用 docker（慢）會因累積服務而逾時；已將 fixture stdio 改用 node `server-everything` 緩解。AT-003 仍偶發逾時（環境競態，非產品缺陷；單獨跑必過）。
4. **fixture 日期**：`convert_time` 的 expected 曾 hardcode 日期；本輪已改用 `get-sum`（無日期依賴）避免跨日失效。
5. **patch 維護**：`@1mcp` 為第三方；`C:\…\mcphub\app` **無** `patch-package` postinstall（`D:\AI-Lab\MCP HUB\app` 有），`npm install` 可能洗掉 C: 的 patch，建議補齊。

---

## 6. 審查焦點（建議 Antigravity 特別檢查）

1. `toolRequestHandlers.js` patch 的**誤判風險**：prefix 對不到已設定 server 時一律回「disabled」——是否會把「打錯工具名的善意錯誤」也誤標為停用？是否可接受？
2. `gateway-controller.js` 的 settle/retry 是否可能在極端情況下掩蓋真實故障（二次 race 才報錯是否足夠）。
3. T-008 的邊界取捨：改測試設定 vs 放寬產品邊界，何者更符合 SPEC。
4. T-009 是否應提供**產品層**的檔案範圍限制（目前依賴下游 MCP 自身 allowed dir），以及 symlink/traversal 的完整性。
5. T-010 的阻塞是否確為環境限制而非可自動化替代。

---

## 7. 一鍵核對指令（唯讀）
```powershell
# 產品測試
cd C:\Users\m8508\mcphub\app; npm test
# patch 可套用性（pristine @1mcp/agent@0.38.2 上）
#   git apply --check "D:\AI-Lab\MCP HUB\app\patches\@1mcp+agent+0.38.2.patch"
# 驗收程式自測
cd "D:\AI-Lab\MCP HUB"; python -B -m unittest discover -s tests/acceptance -p test_checker.py -v
# 讀 state
python -B harness/runner/runner.py read --ticket T-005
```
