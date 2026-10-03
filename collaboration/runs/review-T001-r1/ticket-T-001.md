---
document_title: MCP Hub T-001 Ticket
chinese_title: iPhone 經私人單一入口呼叫兩種 MCP
aka: []
established_date: 2026-10-02
updated_date: 2026-10-02
version: 1.0.0
id: T-001
depends_on: []
---

# T-001：iPhone 經私人單一入口呼叫兩種 MCP

**Status:** TODO — 拆解已確認；尚未實作或通過驗收。
**Blocked by:** 無
**Type:** 使用者功能垂直切片

## 需求追溯

- Scope：S-07、S-09。
- User Stories：US-12、US-15。
- PLAN 驗收：AC-09、AC-10。
- 技術查證：D-01、D-02、D-04 的傳輸部分。
- 原始行為定義以 SPEC.md 為準，不擴張 PLAN.md 範圍。

## What to build

建立最小可用 Gateway 路徑，讓 iPhone 在行動網路上經 Tailscale 與同一個 Open Minis 入口，取得 stdio 與 Streamable HTTP 測試工具的正確結果。

首次連線設定可用終端機。需要的安裝、登入、網路規則另遵循既有授權邊界；本工單文件不等於已執行。



## Acceptance criteria

- [ ] 選定及記錄 Gateway、Open Minis、傳輸協定與兩個無憑證測試 MCP 的實際版本與相容性。
- [ ] 從 iPhone 關閉 Wi-Fi 的情境各呼叫兩個下游工具，與事先定義的結果核對；不得以桌面客戶端替代。
- [ ] 授權裝置可呼叫，未授權來源拒絕；不開公開入口，不收集 Tailscale 憑證。
- [ ] 只用受控、無副作用或安全測試資料的工具；保留可供後續重跑的無機密 fixture。
- [ ] 不要求尚未建立的管理頁；管理頁隔離留在 T-002、T-010 驗證，不宣稱整個 US-12 已驗收。

## 自動驗證

Golden Path step：AT-001。在專案根目錄執行：

```powershell
python -B tests/acceptance/check.py --ticket T-001
```

初始化實際 Gateway，列出工具並執行兩個 fixture 所指定的 tools/call；檢查非錯誤結果及指定 JSON 值，不接受只有工具清單。

實際程式位於 tests/acceptance/check.py；操作契約、fixture 與環境需求見 tests/acceptance/README.md。環境未就緒時回傳非零，不跳過、不輸出假成功。此命令只涵蓋明列的自動檢查，不代表整張工單全部通過。

## 必要補充驗證

必須附 iPhone、Open Minis 版本、行動網路與 Tailscale 的操作證據，以及未授權來源負向測試。

審查者必須逐項核對未被上述自動命令涵蓋的 Acceptance criteria，提供實際來源與限制。僅有自動 PASS 或證據欄位完整，均不足以完成工單。

## 完成與交接

- [ ] 工單限定的自動命令通過，實際輸出及版本可追溯。
- [ ] 全部人工及負向驗收完成；未測不得填 PASS。
- [ ] 技術選擇與查證結果可供下一張沿用，機密不進文件或日誌。
- [ ] 保留測試環境重現方法；明列修改與需清理的測試資源，不自行清理正式服務。
- [ ] 由實際 harness 流程記錄驗證與審查；本文件不代替 runtime state。

