---
document_title: MCP Hub Acceptance Check Contract
chinese_title: MCP Hub 驗證入口與測試契約
aka: []
established_date: 2026-10-02
updated_date: 2026-10-09
version: 1.1.0
---

# 驗證入口與測試契約

check.py 是實際向 Gateway 發出請求並操作管理 UI 的驗證程式，不包含產品實作。程式存在不代表產品測試通過。目前無應用程式或真實 fixture；UI 所需 Playwright 尚未安裝。本輪沒有安裝依賴、啟動服務或連線私人網路。

## 指令與結果

在專案根目錄，以 `python -B tests/acceptance/check.py --ticket T-001` 執行指定工單，其餘使用 T-002 至 T-011。golden_path.json 逐張指向此實際檔案，每個步驟只標記該張工單。T-011 的前置閉包包含全部其他工單，因而可重跑所有檢查。

- exit 0 與 `AUTOMATED_CHECK_PASS`：只表示該張列明的自動部分通過；所有必要人工與其他負向驗收仍需完成。
- exit 1：操作或 assertion 失敗，不能接受。
- exit 2 與 `UNVERIFIED`：缺少明確 fixture、隔離宣告、操作授權或必要環境；不能跳過後當成 PASS。

工單勾選、狀態欄、人工口述、這份文件存在與驗證程式的單元測試均不能取代產品測試。iPhone 實機行動網路、未授權來源及未被自動程式覆蓋的案例，必須有對應的實際操作證據。

## 測試環境前提

1. 在工作區外的專用測試目錄建立隔離環境；不要使用正式 Gateway、既有使用者設定或正式資料。目錄內建立 `.mcp-hub-acceptance`，其內容為 `isolated-test-environment`。標記是防誤操作的約定，不是 OS sandbox。
2. 以 `MCP_HUB_ACCEPTANCE_CONFIG` 指定無機密 JSON fixture 的絕對路徑，並明確設定 `MCP_HUB_ACCEPTANCE_ALLOW_MUTATION=1`。未設定時程式在任何網路操作前失敗。
3. 準備兩個安全、可重現、無憑證的測試服務。T-001、T-002 使用預先配置的服務；新增設定類測試會建立隨機名稱的新服務，檢查完成後只刪除本次建立的隨機服務，不刪除既有設定。測試完保留既有測試設定、日誌與資料供核對；執行中的程序不在保留範圍，依第 6 點停止。
4. UI 驗證需要 Python Playwright 與其可用 Chromium。它用於瀏覽器操作，與產品前後端技術選擇無關。選定相容版本並依授權完成安裝後才能驗證；本輪未安裝。
5. 不要讓測試產物或應用設定落入受 source hash 管理的專案目錄。自動程式使用 `-B` 禁止 bytecode，沒有新增排除規則；若日後必須新增產物位置，明確審閱後再調整 golden_path.json，不排除原始碼或整個 .harness。
6. 每次驗收結束時，不論結果是通過或失敗，都要停止本次啟動的所有程序：對本次的 Gateway config-dir 執行 `node <@1mcp/agent build/index.js> --config-dir <本次 config-dir> --stop`，並結束本次啟動的測試 Hub 與測試服務程序。停止指令的輸出存入本次 sandbox_root 作為證據。背景 Gateway 若未停止，會持續占用連接埠，而且 supervisor 會在 worker 結束後自動把它重新啟動。

## Fixture 欄位

實際值在 T-001／相關工單驗證時取得；不得把下列欄位說明當作已驗證的服務設定。這不是產品設定格式，不提供任何真實密碼或 token。

| 欄位 | 要求 |
| --- | --- |
| isolated | 必須為 true。 |
| sandbox_root | 絕對路徑，必須已存在且有隔離標記。 |
| gateway_url | 實際 Gateway endpoint；只接受 loopback、Tailscale IP 或 .ts.net 名稱，不接受 URL 憑證、query 或 redirect。 |
| protocol_versions | 已查證的可支援協定版本清單，第一項用於 initialize；協商結果不在清單即拒絕。 |
| services | 恰好兩筆，transport 分別為 stdio 與 http。 |
| ui_url | 真實管理頁 URL；只能 loopback。T-002 起需要。 |
| replacement_http | T-004 起需提供不同安全 HTTP endpoint 及不同 expected，讓編輯生效可被觀察。 |
| gateway_log、log_marker | T-008 起需提供 sandbox_root 內的實際日誌及事先產生的已知診斷事件字串。 |
| outside_sentinel | T-009 使用的安全哨兵檔，位於 sandbox_root 內、但在被測 MCP 允許目錄之外；不得使用真實個人資料。 |
| file_allowed、file_denied | 各有 name、call、expected 或 denied_contains，描述真正的允許及拒絕工具請求。 |
| private_gateway_url | T-010 起需要，必须是非 loopback 的私人 Gateway 位址。主機使用此位址仍不等於 iPhone 實測。 |

每筆 services 必須有：name、transport、call、expected、denied_contains。stdio 另有 command 與 arguments 清單，HTTP 另有 url。call 是實際 Gateway 的 tools/call params，包含 name 與 arguments；以 `$SERVICE` 作為由 UI 新增的服務名稱替換點。Gateway 若使用路由工具，在此填實際路由呼叫，不假設工具全部平鋪。

expected 是非空 assertion 清單，每筆包含 path 與 equals。例如 path 指向 `content` 清單中的文字欄位；equals 必須是可重現工具結果，不是任意成功字串。denied_contains 必須來自已查證的拒絕原因；不能以連線逾時或 Gateway 整體故障當成「該服務被停用」。file_denied 的 expected 不使用，必須有明確拒絕內容。

## UI 操作契約

這是實作前選定的可存取介面名稱與測試契約，不是聲稱 UI 已存在；不指定產品框架、API 路由或資料庫。若後續需要修改契約，須同步更新測試及依 harness 流程審閱核准計畫變更。

- 頁面 heading：`MCP Hub`。
- Gateway 按鈕：`啟動 Gateway`、`停止 Gateway`、`重啟 Gateway`。
- Gateway 操作結果在 role=status 呈現：`Gateway 運作中`、`Gateway 已停止`。
- 新增按鈕：`新增 MCP Server`；label：`服務名稱`、`傳輸類型`、`啟動命令`、`命令參數`、`服務 URL`。傳輸選項值為 stdio、http；命令參數欄位接受 JSON argv 清單，不依靠 shell 拼接。
- 套用按鈕：`儲存並套用`；完成訊息在 role=status 呈現 `設定已套用`。只有已生效才呈現成功。提示文字本身仍需人工／補充驗證，測試瀏覽器接受原生確認對話框不構成提示內容已通過。
- 服務以 row 呈現唯一名稱；列內按鈕為 `編輯`、`停用`、`刪除`、`測試連線`。停用及刪除先形成待套用狀態，再由同一套用按鈕生效。
- 健康狀態有精確文字 `可連線`、`已停用`；檢查時間以 time 元素的 datetime 屬性提供有時區 ISO 時間。未檢查及失敗亦需依 SPEC 實作，現有自動子集尚未覆蓋全部狀態。
- 日誌按鈕：`查看日誌`；內容使用 role=log。原始日誌允許其他程序追加，但不能因檢視而截斷或改寫既有內容。

## 完成條件與已知限制

- 自動程式涵蓋每張工單的真實行為子集；完整 acceptance criteria 仍以各工單為準。故障恢復、過期 PID、來源限制及部分 UI 邊界尚需實作階段補上可重現測試與證據，不能在審查時省略。
- initialize／tools/list／tools/call probe 支援 JSON 與 SSE 回應、session header 及協定版本檢查，但不是完整 MCP SDK；不支援自動登入、舊 SSE transport 或 server-to-client 互動工具。只選符合無憑證測試範圍的工具。
- 停用／刪除測試先證明兩服務可用，再要求一個被拒、另一個仍可用。T-009 的單一哨兵檔雜湊只能證明該樣本未變，完整邊界驗收還需穿越、連結與讀寫案例。
- T-011 先重跑各自動子集，再做連續 UI 主流程；其私人 endpoint 請求仍由主機發出。SPEC 的 iPhone 步驟必須再由手機實際完成，不能用 T-011 exit 0 代替。

## 本輪可執行的驗證程式自測

`python -B -m unittest discover -s tests/acceptance -p test_checker.py -v` 檢查 assertion、JSON/SSE 處理、URL 邊界與 11 個命令在缺環境時拒絕通過。測試採記憶體 transport double，不連到產品或網路。這些結果只證明驗證程式的部分行為，不是產品或真實 transport 相容性通過。

參考：[MCP Streamable HTTP 規格](https://modelcontextprotocol.io/specification/2025-06-18/basic/transports)、[Playwright Python locators](https://playwright.dev/python/docs/locators)。本輪依前者處理 JSON／SSE、session 與 protocol headers，依後者使用角色及標籤定位；版本相容性仍須真實環境測試。
