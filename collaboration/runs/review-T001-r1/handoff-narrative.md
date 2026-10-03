# T-001 Handoff — iPhone 經私人單一入口呼叫兩種 MCP

- 日期：2026-10-02
- 執行者：Claude Code（協調者）；iPhone 操作、Tailscale ACL 與 Open Minis 設定由操作者本人執行
- 綁定：review_round 1，source_hash `7f4e5fd6…c0fd`，verification_id `e4615cdacb594dd09c88b7816b1c5249`
- 機器可讀版本：`.harness/inbox/handoff.json`
- 證據目錄：`D:\AI-Lab\MCP-HUB-acceptance\evidence\T-001\`（截圖、gateway 日誌節錄、versions.json、verify-ticket-final.json）

## 技術選擇（D-01、D-02、D-04 傳輸部分）

| 項目 | 選擇 | 理由／查證 |
|---|---|---|
| Gateway | `@1mcp/agent` 0.38.2，Windows 原生 Node 24.19.0 | 單一 `/mcp` 端點聚合 stdio 與 Streamable HTTP 下游。TBXark/mcp-proxy 已排除：依其 `docs/USAGE.md`，每個下游各有一條路徑，不符合單一入口 |
| 遠端入口 | Tailscale Serve，`https://alvin.tail63d20f.ts.net/mcp`，只代理 `/mcp`，限 tailnet | 1MCP 一律掛載 OAuth 路由，非 loopback 綁定會觸發 SDK 的「Issuer URL must be HTTPS」；Serve 讓 Gateway 保持 loopback，也不需要防火牆規則 |
| 來源限制 | Tailscale ACL：主機的 tcp:443 只授權給 iPhone | 其他存取維持原本的全部允許 |
| 測試 MCP | `@modelcontextprotocol/server-everything` 2026.8.31，stdio 與 streamableHttp 各一份 | 無憑證、`get-sum` 結果可重現 |
| 協定 | 2025-11-25、2025-06-18 皆可協商 | check.py 實測 |
| 客戶端 | Open Minis 1.15（build 7，操作者回報）、iOS 18.7 | 截圖：傳輸選項有 HTTP/SSE/STDIO，支援自訂請求頭 |

## 驗收對照

- 自動：AT-001 PASS；兩項破壞測試皆讓檢查失敗（exit 1）。
- iPhone 4G：兩個工具回傳 5 與 42，ACL 前（23:16）與 ACL 後（23:29）各一次；gateway 日誌來源 `100.88.86.52`。
- 未授權來源：WSL 節點 `alvin-1` 在 ACL 後逾時，Gateway 無紀錄；ACL 前同一來源可達。
- 遠端只開 `/mcp`：`/oauth`、`/`、`/health`、`/sse` 皆 404。
- [UNVERIFIED] Open Minis 版本截圖尚未附上。
- [UNVERIFIED] 未從真正的 tailnet 外部主機做探測，僅有設定證據。
- 管理頁隔離屬 T-002、T-010，本工單不宣稱 US-12 已驗收。

## 限制與後續工單需知

1. Open Minis 實際是透過其本機 Linux 環境的 `minis-mcp-cli`（python-httpx）呼叫，不是 App 原生工具呼叫。
2. Minis 環境使用電信 DNS，無法解析 tailnet 名稱；已在其 `/etc/hosts` 加入一行。Minis 更新或重置後可能消失。
3. HTTP 下游重啟後，1MCP 會沿用失效的 session ID（`No valid session ID provided`），直到 Gateway 重啟 → 與 AC-12、D-05 相關，T-005 以後處理。
4. 1MCP 的 `--host` 只接受單一位址；目前只綁 loopback，遠端完全靠 Serve。
5. 1MCP 預設啟用熱重載，已用 `--enable-config-reload false` 關閉，符合 SPEC「儲存並套用」。
6. 工作範圍外的既有狀況：WSL 節點 `alvin-1` 已開啟 Tailscale Funnel，把 `127.0.0.1:8765` 公開到網際網路（Open Minis 的 Local Workspace 透過這條公開路徑連線）。本工單未變更它。

## 需清理的測試資源（未自行清理）

- 程序：Gateway（PID 28224）、HTTP 測試 MCP（PID 5788）、Gateway 底下的 stdio 子程序
- `tailscale serve`：用 `tailscale serve reset` 移除
- Tailscale ACL：還原為原本的預設 policy
- Minis `/etc/hosts` 的那一行
- 隔離目錄：`D:\AI-Lab\MCP-HUB-acceptance\`
- 專案備份：`D:\AI-Lab\MCP HUB\.harness.bak-20261002T211720\`
