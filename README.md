# py-stock-weekly

台股籌碼週期追蹤工具。每日自動抓取大盤與觀察名單個股的三大法人、融資融券、期貨未平倉、集保股權分散、法說會日期、VIX 恐慌指數等資料,存入 SQLite,並輸出 Excel 報表與給 AI 判讀用的正規化 JSON。

> 想了解內部設計原理、各資料源的細節限制,或想自己新增資料源,請見 [ARCHITECTURE.md](ARCHITECTURE.md)。

## 功能

- 抓取大盤與觀察名單個股的三大法人、融資融券、借券賣出、期貨未平倉、價格結構等籌碼資料,以 SQLite 累積歷史(upsert,重複執行不會重複灌資料)
- 交易日曆:依 TWSE 官方休市公告 + 臺北市颱風假公告,自動判斷當天是否為交易日
- 月營收、財報(毛利率/營益率/EPS)、資產負債表等基本面資料
- 集保股權分散表(千張大戶佔比,週更)、VIX 恐慌指數、法說會日期等總經與事件資料
- 自建訊號判斷:自營商連續買賣超、營收連續成長/衰退、PE 河流圖百分位、大戶佔比連續增減週數
- 匯出 Excel 報表與給 AI 判讀用的正規化 JSON,並可設定自動寄信(失敗只印警告,不影響資料寫入)

## 安裝

```bash
git clone https://github.com/ohpargsohp/py-stock-weekly.git
cd py-stock-weekly

python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # macOS / Linux

pip install -r requirements.txt
```

需求:Python 3.9 以上。需能連線到 `www.twse.com.tw`、`openapi.twse.com.tw`、`openapi.taifex.com.tw`、`opendata.tdcc.com.tw`、`mopsov.twse.com.tw`、`api.stlouisfed.org`、`alerts.ncdr.nat.gov.tw` 這些網域(公司網路/代理伺服器若有白名單限制請先確認)。

**(選用)設定寄信與 VIX**:在專案根目錄建立 `.env`(已列入 `.gitignore`,不會進版控):

```env
SENDER_EMAIL=you@gmail.com
SENDER_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_TO=receiver@example.com
FRED_API_KEY=your_fred_api_key
```

`SENDER_APP_PASSWORD` 是 Gmail 的「應用程式密碼」,需先開啟兩步驟驗證後產生:[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)。`FRED_API_KEY` 是 VIX 抓取需要的免費金鑰,註冊即可取得:[fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys)。四個變數任一未設定,對應功能會自動略過,不影響其他資料源。

## 使用

### 基本執行

```bash
python main.py            # 抓今天
python main.py 20260713   # 抓指定日期(格式 YYYYMMDD)
```

### 執行時會發生什麼

1. 依 TWSE 官方休市公告判斷今天是否為交易日,印出提示
2. 掃描 `providers/` 下所有資料源,逐一抓取當日資料並 upsert 進 `data/chip.db`,主控台印出每個 provider 的抓取結果
3. 印出自營商近 6 日買賣方向,連續同向達 5 日以上會提示強烈訊號
4. 若 VIX > 35 印出極端恐慌提示(需先設定 `FRED_API_KEY`)
5. 印出觀察名單個股月營收 YoY 連續成長/衰退達 3 個月以上的提示
6. 印出觀察名單個股 PE 落在自建歷史極端百分位(≤10 或 ≥90,且樣本 ≥60 天)的提示
7. 印出觀察名單個股千張大戶佔比連續增/減達 3 週以上的提示
8. 匯出 `data/chip_report_YYYYMMDD.xlsx`
9. 匯出 `data/weekly_scan_YYYYMMDD.json`
10. 寄出報表(Excel + JSON 附件)至 `.env` 裡設定的 `EMAIL_TO`

`data/` 底下的輸出檔案(資料庫、Excel、JSON)不會進 git,每台機器/每次 clone 都是從零開始累積歷史。

### PE 河流圖歷史回補(選用,建議跑一次)

PE 河流圖統計靠每天累積的 PE 資料才有意義,剛裝好時樣本幾乎是 0。可以跑一次性回補腳本,把過去幾年的每日 PE 補進資料庫:

```bash
python scripts/backfill_pe_history.py            # 回補近 3 年(預設)
python scripts/backfill_pe_history.py --years 5  # 回補近 5 年
```

只需跑一次,之後 `main.py` 每天正常執行就會持續累積,不用重跑。

### 每日自動排程(選用)

程式本身不會自己排程,要「每日自動抓取」需交給作業系統的排程工具,在收盤後執行(台股約 13:30 收盤,建議排 14:00 之後):

```powershell
# Windows(工作排程器)
schtasks /create /tn "StockChipTracker" /tr "python d:\python\stock-chip-tracker\main.py" /sc daily /st 14:30
```

```bash
# macOS / Linux(crontab -e,每個交易日 14:30 執行)
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

## 資料來源一覽

完整說明(每個來源的更新頻率、限制、怪癖)見 [ARCHITECTURE.md](ARCHITECTURE.md#資料來源)。

| 資料 | 頻率 | 來源 |
| --- | --- | --- |
| 大盤指數、三大法人、融資融券、期貨未平倉 | 逐日 | TWSE / TAIFEX |
| 個股三大法人、融資融券、借券賣出、價格結構、收盤價/PE | 逐日 | TWSE |
| 月營收、財報(損益表/資產負債表) | 逐月/逐季 | TWSE OpenAPI |
| 集保股權分散表(千張大戶佔比) | 逐週 | TDCC OpenData |
| VIX 恐慌指數 | 逐日(需 API Key) | FRED |
| 法人說明會(法說會)日期 | 依公告 | MOPS |

## 設定

編輯 `config.py`:

- `WATCHLIST`:觀察名單(股票代號 → 名稱),個股相關 provider 只抓這裡列出的標的
- `DB_PATH` / `EXCEL_PATH` / `JSON_PATH`:輸出檔案路徑
- `SLEEP_SEC`:每個 provider 抓取後的間隔秒數,避免對 API 過於頻繁請求

收件地址 `EMAIL_TO` 與 `FRED_API_KEY` 放在 `.env`(見上方「安裝」),不放進 `config.py`,避免個人信箱與金鑰進版控。
