# 審查回應 — MCP HUB T-005～T-009

> 對應：Antigravity 獨立審查（針對 `REVIEW_WORKORDER_T005-T009.md`）
> 日期：2026-10-12

## 審查結論採納

Antigravity 結論為 **PASS（無 blocking issue）**；本輪已逐項核對其證據：
- 5 張 receipt 皆 `all_passed=true`、AT 全 PASSED rc=0、`source_hash` 與 review 一致。
- `npm test` 76/76；`test_checker.py` 13/13；patch `git apply --check` exit 0。
- state `PAUSED`（DEC-001）合規；T-010/T-011 阻塞判定成立。

## 逐項處置

### #4 T-009 測試 shim symlink/junction 逃逸 — **已修補並實證（本輪動作）**
- **重現**：於 allowed 目錄建立 junction 指向範圍外，直接驅動 `file-mcp.mjs` 讀 `<allowed>\escape-dir\t009-sentinel.txt` → **成功讀出** `sentinel-content-must-not-change`（確認漏洞）。
- **修補**：`file-mcp.mjs` 改用 `fs.realpathSync` 解析**實體**路徑（含父目錄 reparse point）後再作 containment 比對。
- **回歸（直接 stdio 測試）**：
  - `allowed`（範圍內檔）→ 成功 `allowed-content-ok`
  - `denied-direct`（範圍外檔）→ `Access denied`
  - `escape-junction`（經 junction 逃逸）→ **`Access denied`（已阻擋）**
- **處置**：T-009 已 COMPLETE 且該 finding 原屬 non-blocking（review 已誠實標註 limitation），**不重開工單**；此修補為測試基礎設施強化，T-011 整合驗收重跑 check_009 時將使用已強化的 shim。（symlink 需管理員權限，故以 junction 等效重現；測試產物已清除。）

### #1 patch「deleted/unknown → disabled」語義混淆 — **接受為 V1 技術債**
- 確認：`toolRequestHandlers.js` patch 對 prefix 對不到已設定 server 者回含 `disabled` 的拒絕。
- 影響：僅語義不精準，仍 `isError:true` 且阻斷執行，**無安全漏洞**。
- 決策：V1 acceptance 下接受；正式版應改回標準 `not_found`／`ServerNotFound` 並調整測試斷言。已記錄於下方「技術債」。

### #2 gateway-controller settle/retry 延時 — **接受（fail-closed 已確認）**
- 確認：settle 後仍須 `status()` 明確取得 `running`/`stopped`，否則回 `error`，**不會偽報成功**。
- 風險：連續兩次 race 最壞可累積 60～90s，可能觸發前端/Playwright 逾時。列為已知效能風險，非正確性問題。

### #3 T-008 邊界取捨 — **維持現狀（與審查一致）**
- 採納審查意見：維持 `configDir` 為日誌邊界（最小權限），測試設定回歸產品預設；不放寬至 sandbox root。

### #5 T-010 阻塞 — **確認成立**
- `check_010` 強制 `remote_only=True` 拒絕 loopback；本機 `tailscale status` = `NoState`。任何 local mock 冒充遠端皆屬造假，不採用。T-011 依賴 T-010，連帶阻塞。

## 技術債（後續工單應納入）

1. `@1mcp` patch：把 removed/unknown server 的拒絕語義由 `disabled` 改為精確的 `not_found`，並同步更新 acceptance fixture 斷言。
2. `C:\Users\m8508\mcphub\app` 補 `patch-package` + postinstall，避免 `npm install` 洗掉 @1mcp patch。
3. 驗收 `verify-ticket` 連續執行的環境競態（AT-003 偶發逾時）可考慮 per-step 環境重置；目前以快速 node stdio fixture 緩解。
4. T-009 後續可補 symlink 專用斷言（本輪已強化 shim，未納入正式 AT）。
