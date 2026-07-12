# py-stock-weekly

台股籌碼週期追蹤工具。每日自動抓取大盤與觀察名單個股的三大法人、融資融券、期貨未平倉等籌碼資料,存入 SQLite,並輸出 Excel 報表與給 AI 判讀用的正規化 JSON。

## 功能

- 抓取大盤與個股籌碼資料,以 SQLite 累積歷史(以日期為主鍵,重複執行會 upsert,不會重複灌資料)
- 自營商(自行買賣)連續買/賣超天數判斷,連續 5 日以上同向視為強烈訊號
- 匯出 Excel 報表(`data/chip_report_YYYYMMDD.xlsx`),每張資料表一個分頁,依日期新到舊排序
- 匯出正規化 JSON(`data/weekly_scan_YYYYMMDD.json`),只放實際抓到的資料,抓不到的欄位列在 `data_quality.unavailable`,不會用假數字填充
- 執行完畢後自動寄出報表(Excel + JSON 附件),未設定寄信帳密則自動略過,不中斷主流程

## 資料來源

| Provider | 資料表 | 說明 | 來源 API |
| --- | --- | --- | --- |
| `market_index.py` | `market_index` | 大盤加權指數收盤/漲跌/成交量 | TWSE FMTQIK |
| `market_inst.py` | `market_chip` | 大盤三大法人買賣超(含自營商自行買賣) | TWSE BFI82U |
| `market_margin.py` | `market_margin` | 全市場融資融券餘額 | TWSE MI_MARGN |
| `stock_inst.py` | `stock_chip` | 觀察名單個股三大法人買賣超 | TWSE T86 |
| `margin_balance.py` | `margin_balance` | 觀察名單個股融資融券餘額 | TWSE MI_MARGN |
| `stock_quote.py` | `stock_quote` | 觀察名單個股收盤價/本益比/股價淨值比 | TWSE BWIBBU_d |
| `foreign_futures_oi.py` | `foreign_futures_oi` | 外資期貨未平倉(僅回傳最新交易日) | TAIFEX OpenAPI |

## 安裝

```bash
pip install -r requirements.txt
```

寄信功能需在專案根目錄建立 `.env`(不會進 git):

```env
SENDER_EMAIL=you@gmail.com
SENDER_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
```

`SENDER_APP_PASSWORD` 是 Gmail 應用程式密碼,不是登入密碼。未設定這兩個變數時會略過寄信,不影響抓取與匯出報表。

## 使用

```bash
python main.py            # 抓今天
python main.py 20260713   # 抓指定日期(格式 YYYYMMDD)
```

執行後會依序:

1. 掃描 `providers/` 下所有資料源,抓取當日資料並 upsert 進 `data/chip.db`
2. 印出自營商近 6 日買賣方向,連續同向達 5 日以上會提示強烈訊號
3. 匯出 `data/chip_report_YYYYMMDD.xlsx`
4. 匯出 `data/weekly_scan_YYYYMMDD.json`
5. 寄出報表(Excel + JSON 附件)至 `config.EMAIL_TO`(需先設定 `.env`)

`data/` 底下的輸出檔案不會進 git(已列入 `.gitignore`)。

## 設定

編輯 `config.py`:

- `WATCHLIST`:觀察名單(股票代號 → 名稱),個股相關 provider 只抓這裡列出的標的
- `DB_PATH` / `EXCEL_PATH` / `JSON_PATH`:輸出檔案路徑(實際匯出檔名會自動加上日期後綴)
- `SLEEP_SEC`:每個 provider 抓取後的間隔秒數,避免對 API 過於頻繁請求
- `EMAIL_TO`:報表收件地址

## 架構

```text
main.py               進入點:載入 provider → 抓取 → 存 DB → 分析 → 匯出報表
config.py             觀察名單與路徑設定
core/
  base.py             DataProvider 抽象基底類別
  registry.py         自動掃描 providers/ 底下的模組並實例化
  storage.py          SQLite 存取(建表、upsert)
  analysis.py         籌碼分析(如自營商連續方向)
  report.py           匯出 Excel
  export_json.py      組出給 AI 判讀用的正規化 JSON
  mailer.py           寄送報表(Gmail SMTP,讀取 .env 帳密)
providers/            各資料源實作,每個檔案對應一個 DataProvider 子類別
```

新增資料源時,只需在 `providers/` 底下新增一個繼承 `DataProvider` 的類別(實作 `name`、`schema`、`fetch()`),不需修改 `main.py`、`storage.py` 或其他 provider,`registry.py` 會自動掃描並載入。
