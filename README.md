# Codex-NPB

NPB 專用的全場讓分與大小分評估工具。這個版本把 2026-08-14 對話中使用的模型假設、盤口計算方式與可核對紀錄整理成可攜式 Python 專案。

## 核心原則

- 不直接套用 MLB 得分參數；每場由 NPB 資料產生主客隊預期得分。
- 使用獨立負二項分布，保留 NPB 低得分與過度離散特性。
- 將規定局數平手的一部分保留為 12 局後和局，其餘分配到一分差結果。
- 原生處理 `7+50`、`6-50`、`2-25` 等台灣尾盤的部分輸贏。
- 只有 EV 至少 4%、模型與去水市場差至少 3 個百分點，且盤型、先發、打線與資料完整度均確認，才可標記 `FORMAL`。
- `WATCH`、`INVALID_STALE`、`PASS` 與實際下注分開保存。
- 單注最高 1,000 單位，預設 0.25 Kelly；不輸出串關。

## 安裝與測試

```powershell
git clone https://github.com/GizzyJeans/Codex-NPB.git
cd Codex-NPB
py -m venv .venv
.venv\Scripts\Activate.ps1
py -m pip install -e .
py -m unittest discover -s tests -v
```

專案只使用 Python 標準函式庫。若不想安裝，也可以設定 `PYTHONPATH=src` 後直接執行模組。

## 分析單一市場

```powershell
codex-npb examples/giants_dragons_under.json
```

輸入檔包含預期得分、分布離散度、市場種類、台灣尾盤及資料確認狀態。輸出包括：

- 主客隊預期得分與最可能比分
- 和局與各分差機率
- 全贏、部分贏、走盤、部分輸及全輸機率
- 公平賠率、市場去水機率、EV、最低接受賠率
- 0.25 Kelly 建議注碼及 `FORMAL/WATCH/INVALID_STALE/PASS`

`1-5` 這類一位數尾碼會被拒絕，必須先由平台規則確認並改寫成明確比例，避免把 5%、50% 或平台縮寫混為一談。

## 紀錄與重現性

- `records/2026-08-13/results_only.csv`：只有官方結果，沒有可證明的賽前模型輸出，因此不補造機率。
- `records/2026-08-14/game_projections.csv`：六場賽前得分分布摘要與正式結果。
- `records/2026-08-14/candidates.csv`：當時的觀察候選；所有實際注碼均為 0。
- `records/2026-08-14/settlements.csv`：事後影子結算，與實際損益分開。
- `records/ledger.jsonl`：匯入事件的 SHA-256 雜湊鏈。
- `reports/2026-08-14.md`：該日比較報告。

驗證紀錄鏈：

```powershell
codex-npb-ledger verify records/ledger.jsonl
```

這批歷史資料是在 2026-08-15 從聊天內容匯入，不應被描述成預先寫入硬碟的 prospective ledger。之後的新場次應在開賽前即時追加，才能納入真正的前瞻驗證。

## 資料狀態

本倉庫目前保存模型核心與可核對歷史快照，不包含自動抓取器。賽程、先發、打線、登錄抹消、牛棚、天氣及市場價格仍須在每次分析時從公開來源更新；無法取得的欄位不得假設已取得。

官方結果來源：

- [NPB 2026-08-13](https://npb.jp/bis/2026/games/gm20260813.html)
- [NPB 2026-08-14](https://npb.jp/bis/2026/games/gm20260814.html)

## 免責聲明

本專案供模型研究與紀錄驗證使用，不保證獲利。單日結果不能證明模型有效；任何投注決策仍須確認平台結算規則、最新先發、正式打線與可成交價格。
