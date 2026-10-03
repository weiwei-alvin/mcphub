---
document_title: MCP Hub V1 Ticket Index
chinese_title: MCP Hub 第一版工單索引與驗證狀態
aka: []
established_date: 2026-10-02
updated_date: 2026-10-02
version: 1.0.0
---

# 正式工單

本表的狀態欄由每次工單狀態轉移後人工同步，權威來源是 `.harness/state.json`（用 `python -B harness/runner/runner.py read` 讀取）。本表若與該檔不一致，以 state.json 為準。

狀態欄最後同步：2026-10-03，T-002 review-verdict PASS 之後。

| 工單 | 交付結果 | 直接前置 | 狀態 |
| --- | --- | --- | --- |
| [T-001](.harness/tickets/T-001.md) | iPhone 經私人單一入口呼叫兩種 MCP | 無 | COMPLETE |
| [T-002](.harness/tickets/T-002.md) | 從本機單一入口安全控制 Gateway | T-001 | COMPLETE |
| [T-003](.harness/tickets/T-003.md) | 從管理頁新增並安全套用 MCP | T-002 | IN_PROGRESS |
| [T-004](.harness/tickets/T-004.md) | 編輯既有 MCP 並持久生效 | T-003 | TODO |
| [T-005](.harness/tickets/T-005.md) | 停用 MCP 並阻止後續呼叫 | T-003 | TODO |
| [T-006](.harness/tickets/T-006.md) | 刪除 MCP 設定並阻止後續呼叫 | T-003 | TODO |
| [T-007](.harness/tickets/T-007.md) | 顯示下游檢查結果並主動測試連線 | T-005 | TODO |
| [T-008](.harness/tickets/T-008.md) | 唯讀查看 Gateway 日誌 | T-003 | TODO |
| [T-009](.harness/tickets/T-009.md) | 限定檔案 MCP 的實際操作範圍 | T-003 | TODO |
| [T-010](.harness/tickets/T-010.md) | iPhone 使用管理後的服務並於離線後恢復 | T-003 | TODO |
| [T-011](.harness/tickets/T-011.md) | 完成 V1 整合驗收並交付證據 | T-004、T-006、T-007、T-008、T-009、T-010 | TODO |

## 本輪交付與核對

- 建立 11 張 .harness/tickets/T-NNN.md；每張有 id、depends_on、需求來源、單一結果、完整驗收、自動子集及必要補充證據。
- 建立 [.harness/golden_path.json](.harness/golden_path.json)，共 11 個 AT 步驟；每個只引用自身工單，依赖由工單 DAG 約束。T-011 的前置閉包含其他全部工單。
- 建立 [驗證程式](tests/acceptance/check.py)、[驗證契約](tests/acceptance/README.md) 與 [驗證程式自測](tests/acceptance/test_checker.py)。没有產品程式、安裝或服務設定變更。
- 結構檢查已通過：11 個工單、有效且無循環的依賴、全部 15 個 US 涵蓋、每張有存在的可執行驗證檔案。
- 驗證程式自測 9 項通過；其中一項逐一執行 11 個工單命令，證明缺少 fixture 時全部 exit 2／UNVERIFIED，不會回報自動通過。JSON／SSE 自測使用記憶體 double，不是 Gateway 相容性證據。
- 實際執行：`python -B -m unittest discover -s tests/acceptance -p test_checker.py -v`，exit 0；另用 Python 做 AST／JSON／DAG／追溯與命令檔案檢查。
- 目前 Python 環境未安裝 Playwright 與 jsonschema，工作區也無 runner／state。未執行 set-ready-for-gate，不宣稱正式 Gate 通過，不代操其他專案的 state。

## 實作進度（依 runtime state）

- **T-001**：COMPLETE。驗收 receipt `verifications/0e3d7856b7db4620be736e7fd8c5c7cc.json`，review r1 PASS。真實 iPhone 證據與未驗證項（Open Minis 版本無截圖、無非 tailnet 來源探測、呼叫走 Minis 內的 `minis-mcp-cli`）記於 `.harness/reviews/cf6fd3e4eb514f56907448a558437d2c.json`。
- **T-002**：COMPLETE。驗收 receipt `verifications/cdeb0a47e34543b68496626f36d6076c.json`，review r1 PASS（`reviews/abee61ec688a40f8874a7494ae15eb1e.json`）。人工實測完整紀錄見 `.harness/review-notes/T-002.md`。
- **T-003**：IN_PROGRESS，尚未開始實作。
- T-004 ~ T-011：TODO。

### 從 T-002 帶出的未結項目

1. **AC-5 缺 iPhone 直接證據**，在 T-010 之前必須補：由操作者從 iPhone 開啟管理頁 URL，記錄連線被拒。該標準在 T-002 的 review payload 中記為 `UNVERIFIED`／non-critical，而非 PASS。詳細理由見 `.harness/review-notes/T-002.md`。
2. **F-01（歸 T-007）**：`app/bin/launch.js` 固定 1.5 秒後開瀏覽器，不等 server ready；3100 被占用時使用者會看到無關頁面而非錯誤。
3. **F-02**：`unknown` 狀態在 UI 中無錯誤樣式（`app/public/index.html` 的 CSS 只為 running／stopped／error 上色）。
4. **F-03**：管理 API 無認證、無 Origin 檢查。任意網頁的 simple cross-origin POST 可停止或重啟 Gateway。PLAN-5／PLAN-6 未將管理頁認證列入 V1，屬已記錄的威脅模型限制。
5. **F-04**：跨使用者本機存取 `127.0.0.1:3100` 未測。
6. **下游失效不可由 Gateway readiness 偵測**：殺掉 3051 下游後 Hub 仍報 `running`、`/health/ready` 仍 200，而 http 工具回 `-32603`。此為 T-007 的分層健康狀態要處理的問題。

### 目前建置與後續工單的落差

`app/public/` 目前只有 Gateway 控制（啟動／停止／重啟 + 狀態文字）。`tests/acceptance/check.py` 從 T-003 起會操作的 `新增 MCP Server`、`儲存並套用`、服務列表、編輯／停用／刪除、連線檢查、日誌面板**尚不存在**；AT-003 之後的步驟會失敗。

## Audit 結果

| 條件 | 本輪判定 | 證據與限制 |
| --- | --- | --- |
| TKT-1 需求追溯 | 文件檢查通過 | 每張列出 US、Scope、AC；所有 15 個 US 均涵蓋。 |
| TKT-2 單一結果 | 文件核對通過 | 沿用使用者確認的 11 張。T-003 的新增、套用、恢復為安全生效的完整結果。 |
| TKT-3 垂直切片 | 文件核對通過 | 功能工單包含必要介面、邏輯、資料與測試，不拆成前後端獨立交付。 |
| TKT-4 技術工單 | 文件核對通過 | 只有 T-011 為跨功能整合驗收，明列無法歸屬單一故事的理由與独立證據。 |
| TKT-5 可執行驗證 | 入口與 assertion 已建立；真實環境未驗證 | 每張都有實際程式與結果斷言，不使用固定成功輸出。缺環境時已證明非零；UI、Gateway、iPhone 及全部產品行為仍未測。 |
| TKT-6 依賴 | 靜態檢查通過 | 同批引用有效、無循環、編號符合前置顺序；尚未經正式 runner 核對。 |

## 實作前的流程缺口

1. 依既有安裝與設定授權規則接入本專案 runner，確認相容 jsonschema；不得在其他專案初始化或修改其 state，也不得虛構 PASS。這是所選 harness 的流程前提，不新增產品功能。
2. 初始 state 必須由 runner init 建立；提交 ready-for-gate 後，由操作者審核並記錄 TICKETS Gate。使用者對拆解的確認不等同已在 runner 記錄的 Gate。
3. T-001 最先可執行。其真實 iPhone、Tailscale 及 Gateway 前提尚未就緒；UI 相關的 Playwright／Chromium 依賴於需要時再處理。本輪不因工具缺少而自動安裝。
4. 後續實作不得把自動子集通過當成整張完成。每張 acceptance criteria 中未自動化的項目都要實測，並在 review 中提供來源與 limitations。
5. T-011 的自動與手機流程較長，正式執行前依實測設定 runner timeout；不可為躲避逾時而刪除驗收步驟。測試產物留在隔離環境，保持專案 source hash 穩定。

## 最小下一步

1. **T-003**：從管理頁新增 MCP 並安全套用。`app/public/` 需要新增服務表單（服務名稱、傳輸類型、啟動命令／命令參數、服務 URL）與「儲存並套用」控制，後端需新增寫入 gateway `mcp.json` 的路由，並依 SPEC 實作「驗證後才套用、套用失敗回復上一份可用設定」。AT-003（`check.py --ticket T-003`）會以 Playwright 實際新增 stdio + http 兩筆並經 Gateway 呼叫驗證。
2. **AC-5 的 iPhone 補證**必須在 T-010 之前完成，不阻擋 T-003。
3. F-01 與下游 readiness 問題記入 T-007，不要在 T-003 順手做。
4. 安裝、登入與網路變更仍需先列明範圍及回復方式；不重問已確認的產品需求。

## 本檔與 runtime state 的關係

本檔的狀態欄是人工同步的摘要，權威來源為 `.harness/state.json`。詳見狀態欄上方的說明。

