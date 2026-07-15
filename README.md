# py-stock-weekly

台股籌碼週期追蹤工具。每日自動抓取大盤與觀察名單個股的三大法人、融資融券、期貨未平倉等籌碼資料,存入 SQLite,並輸出 Excel 報表與給 AI 判讀用的正規化 JSON。

## 功能

- 抓取大盤與個股籌碼資料,以 SQLite 累積歷史(以日期為主鍵,重複執行會 upsert,不會重複灌資料)
- 自營商(自行買賣)連續買/賣超天數判斷,連續 5 日以上同向視為強烈訊號
- 匯出 Excel 報表(`data/chip_report_YYYYMMDD.xlsx`),每張資料表一個分頁,依日期新到舊排序
- 匯出正規化 JSON(`data/weekly_scan_YYYYMMDD.json`),只放實際抓到的資料,抓不到的欄位列在 `data_quality.unavailable`,不會用假數字填充
- 執行完畢後自動寄出報表(Excel + JSON 附件),未設定寄信帳密則自動略過,不中斷主流程

## 原理

### 1. Provider 外掛架構

每個資料來源(大盤指數、三大法人、融資融券…)都是 `providers/` 底下一個獨立的 `DataProvider` 子類別,只需實作:

- `name`:對應的 SQLite 資料表名
- `schema`:欄位名 → SQL 型別的字典
- `pk`:主鍵欄位(用來判斷「這筆資料是不是已經抓過了」)
- `fetch(date_str)`:呼叫外部 API,回傳 `list[dict]`,無資料(如休市)回傳 `[]`

`core/registry.py` 在程式啟動時用 `pkgutil.iter_modules` 掃描整個 `providers/` 目錄,自動找出所有 `DataProvider` 子類別並實例化,不需要在 `main.py` 手動註冊。因此新增一個資料源只要新增一個檔案,其他程式碼完全不用動。

### 2. 冪等寫入(Upsert)

`core/storage.py` 用 SQLite 的 `INSERT ... ON CONFLICT(pk) DO UPDATE` 寫入資料。每個 provider 的 `pk`(通常是 `trade_date`,個股類再加 `stock_id`)保證同一天重複執行 `python main.py` 不會產生重複資料,只會覆蓋成最新結果。這代表可以放心地對同一天重跑,或補抓過去某一天的資料而不必擔心弄髒資料庫。

### 3. 資料品質:寧缺勿濫

`core/export_json.py` 組出的 JSON 只放「實際查得到」的欄位。查不到的項目(例如大盤股價淨值比沒有官方 API、休市與抓取失敗目前無法區分)會明確列在 `data_quality.unavailable` 並附上原因,而不是用 0 或估計值填充。這是為了給 AI 或人判讀時能明確分辨「沒有這個資訊」跟「這個資訊是 0」,避免誤判。

### 4. 籌碼訊號判斷

`core/analysis.py` 的 `dealer_streak` 抓出大盤自營商(自行買賣)最近 N 日的買賣方向,`main.py` 與 `export_json.py` 各自判斷是否連續 5 日以上同向——這是目前唯一內建的訊號規則,選擇自營商自行買賣是因為它反映了自營商真正的方向性部位(相對於避險部位)。

### 5. 執行流程

```text
main.py run()
  ├─ 逐一走訪 load_providers() 回傳的每個 provider
  │    ├─ ensure_table()  若表不存在則建立
  │    ├─ fetch(date_str) 呼叫外部 API 拿當日資料
  │    ├─ upsert()        寫入 SQLite(冪等)
  │    └─ sleep(SLEEP_SEC) 禮貌性間隔,避免打爆對方 API
  ├─ dealer_streak()      判斷自營商連續方向,印出主控台提示
  ├─ export_excel()       整庫匯出成 Excel,一表一分頁
  ├─ export_weekly_scan() 整庫組成正規化 JSON
  └─ send_report()        寄出 Excel + JSON(未設定信箱則自動略過)
```

## 安裝

### 1. 需求

- Python 3.9 以上(開發環境為 3.14)
- 一組 Gmail 帳號 + 應用程式密碼(僅寄信功能需要,非必要)

### 2. 下載專案

```bash
git clone https://github.com/ohpargsohp/py-stock-weekly.git
cd py-stock-weekly
```

### 3. (建議)建立虛擬環境

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate
```

### 4. 安裝套件

```bash
pip install -r requirements.txt
```

### 5. (選用)設定寄信功能

在專案根目錄建立 `.env`(此檔案已列入 `.gitignore`,不會進版控):

```env
SENDER_EMAIL=you@gmail.com
SENDER_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_TO=receiver@example.com
```

`SENDER_APP_PASSWORD` 是 Gmail 的「應用程式密碼」,不是登入密碼,需先在 Google 帳戶開啟兩步驟驗證後才能產生:[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)。`EMAIL_TO` 是報表收件地址。三個變數任一未設定,程式會自動略過寄信,不影響抓取與匯出報表。

## 使用

### 基本執行

```bash
python main.py            # 抓今天
python main.py 20260713   # 抓指定日期(格式 YYYYMMDD)
```

### 執行時會發生什麼

1. 掃描 `providers/` 下所有資料源,逐一抓取當日資料並 upsert 進 `data/chip.db`,主控台會印出每個 provider 的抓取結果
2. 印出自營商近 6 日買賣方向,連續同向達 5 日以上會提示強烈訊號
3. 匯出 `data/chip_report_YYYYMMDD.xlsx`
4. 匯出 `data/weekly_scan_YYYYMMDD.json`
5. 寄出報表(Excel + JSON 附件)至 `.env` 裡設定的 `EMAIL_TO`(需先完成上方「設定寄信功能」步驟)

`data/` 底下的輸出檔案(資料庫、Excel、JSON)不會進 git(已列入 `.gitignore`),每台機器/每次 clone 都是從零開始累積歷史。

### 每日自動排程(選用)

程式本身不會自己排程,要「每日自動抓取」需交給作業系統的排程工具,在收盤後執行(台股約 13:30 收盤,建議排 14:00 之後):

#### Windows(工作排程器 Task Scheduler)

```powershell
schtasks /create /tn "StockChipTracker" /tr "python d:\python\stock-chip-tracker\main.py" /sc daily /st 14:30
```

#### macOS / Linux(cron)

```bash
# crontab -e,加入以下這行(每個交易日 14:30 執行)
30 14 * * 1-5 cd /path/to/py-stock-weekly && /usr/bin/python3 main.py
```

### 查詢歷史資料

所有歷史資料都存在 `data/chip.db`,可直接用任何 SQLite 工具查詢,例如:

```bash
python -c "
import sqlite3
conn = sqlite3.connect('data/chip.db')
for row in conn.execute('SELECT * FROM stock_chip ORDER BY trade_date DESC LIMIT 10'):
    print(row)
"
```

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

## 設定

編輯 `config.py`:

- `WATCHLIST`:觀察名單(股票代號 → 名稱),個股相關 provider 只抓這裡列出的標的
- `DB_PATH` / `EXCEL_PATH` / `JSON_PATH`:輸出檔案路徑(實際匯出檔名會自動加上日期後綴)
- `SLEEP_SEC`:每個 provider 抓取後的間隔秒數,避免對 API 過於頻繁請求

收件地址 `EMAIL_TO` 不在 `config.py` 裡,而是跟寄信帳密一起放在 `.env`(見上方「設定寄信功能」),避免個人信箱進版控。

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

## 新增資料源

只需在 `providers/` 底下新增一個繼承 `DataProvider` 的類別,不需修改 `main.py`、`storage.py` 或其他 provider,`registry.py` 會自動掃描並載入。最小範例:

```python
# providers/example.py
from core.base import DataProvider

class ExampleProvider(DataProvider):
    name = "example_table"          # SQLite 資料表名
    pk = ["trade_date"]             # 主鍵,決定 upsert 的判斷依據
    schema = {
        "trade_date": "TEXT",
        "some_value": "REAL",
    }

    def fetch(self, date_str):
        # 呼叫外部 API,回傳 list[dict],無資料回 []
        return [{"trade_date": date_str, "some_value": 123.4}]
```
