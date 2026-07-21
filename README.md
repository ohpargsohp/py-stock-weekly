# py-stock-weekly

台股籌碼週期追蹤工具。每日自動抓取大盤與觀察名單個股的三大法人、融資融券、期貨未平倉、集保股權分散、法說會日期、VIX 恐慌指數等資料,存入 SQLite,並輸出 Excel 報表與給 AI 判讀用的正規化 JSON。

## 目錄

- [功能](#功能)
- [原理](#原理)
- [安裝](#安裝)
- [使用](#使用)
- [資料來源](#資料來源)
- [設定](#設定)
- [架構](#架構)
- [新增資料源](#新增資料源)

## 功能

### 籌碼面(逐日)

- 抓取大盤與個股籌碼資料,以 SQLite 累積歷史(以日期為主鍵,重複執行會 upsert,不會重複灌資料)
- 交易日曆:依 TWSE 官方休市公告 + 臺北市天然災害停止上班(颱風假)公告判斷當天是否為交易日,把「當天沒有資料」明確拆成「休市」跟「無法判斷」,不再是含糊不清的單一說明
- 自營商(自行買賣)連續買/賣超天數判斷,連續 5 日以上同向視為強烈訊號
- 借券賣出餘額:觀察名單個股借券賣出餘額與當日賣出/還券增減,可作為法人/大戶放空壓力的參考訊號
- 個股價格結構:開高低收、單日漲跌幅、成交量/成交金額,支援乖離率、量價結構等技術面判讀

### 基本面(逐月/逐季)

- 月營收動能:YoY/MoM 增減幅(TWSE 直接提供)+ 連續正/負成長月數(自行累積歷史算出)
- 毛利率/營益率/淨利率/EPS:自財報(綜合損益表)原始金額自行計算,涵蓋一般業公司
- 資產負債表:資產/負債/權益總額、負債比率、每股參考淨值,涵蓋一般業公司;依財報法定申報截止日判斷資料庫是否已有最新一期,已有就不重複打 API

### 大戶籌碼(逐週)

- 集保股權分散表:觀察名單個股千張大戶(持股≥1,000張)人數/佔集保庫存比例,TDCC 每週公布一次;連續增/減週數可作為大戶籌碼集中/派發的參考訊號

### 總經與公司事件

- VIX 恐慌指數(FRED):支援「VIX>35」這類極端恐慌的總經條件單訊號(需自行申請免費 API Key)
- 法人說明會(法說會)日期:觀察名單個股法說會日期、時間、地點、擇要訊息(MOPS)

### 自建指標

- PE 河流圖(自建版):每天累積個股 PE,算出目前 PE 落在自己歷史分布的第幾百分位、歷史極值——不是官方河流圖,樣本量取決於累積了多久(可用 `scripts/backfill_pe_history.py` 一次回補歷史)

### 輸出

- 匯出 Excel 報表(`data/chip_report_YYYYMMDD.xlsx`),每張資料表一個分頁,依日期新到舊排序
- 匯出正規化 JSON(`data/weekly_scan_YYYYMMDD.json`),只放實際抓到的資料,抓不到的欄位列在 `data_quality.unavailable`,不會用假數字填充
- 執行完畢後自動寄出報表(Excel + JSON 附件),未設定寄信帳密則自動略過;寄信本身失敗(例如帳密錯誤、網路問題)也只會印警告,不會讓整支程式以錯誤結束——資料在寄信之前就已經寫入硬碟,寄信只是錦上添花

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

`core/export_json.py` 組出的 JSON 只放「實際查得到」的欄位。查不到的項目(例如大盤股價淨值比沒有官方 API)會明確列在 `data_quality.unavailable` 並附上原因,而不是用 0 或估計值填充。這是為了給 AI 或人判讀時能明確分辨「沒有這個資訊」跟「這個資訊是 0」,避免誤判。

### 4. 落後資料:各自回報自己的日期,不硬湊 anchor

`export_json.py` 以 `market_chip`(大盤三大法人)的最新日期當作整份報告的 `as_of` anchor,但不是每個資料源都能跟上這個日期——TAIFEX 期貨未平倉 API 沒有日期參數,永遠只回傳「它自己的」最新交易日;TWSE 個股三大法人/收盤價 API 有時也會比大盤指數慢好幾天更新;TDCC 集保股權分散表更是每週才更新一次。這些區塊(`foreign_futures_oi`、`watchlist`、`watchlist[].holder_distribution`)因此改以**各自資料源本身最新的一天**為準,不要求跟 anchor 同一天,並在每筆資料上明確標出自己的 `trade_date`/`as_of`,避免把過期資料誤標成當天的。早期版本曾經要求同一天才合併,結果只要任一資料源更新較慢,整個區塊就會在 JSON 裡完全消失——即使 Excel(不做日期篩選,整表原樣匯出)裡明明還看得到。

### 5. 籌碼訊號判斷

`core/analysis.py` 目前內建兩組「連續同向」訊號規則,回傳格式都是 `(日期, 訊號值)` 的 list,方便呼叫端(`main.py`、`export_json.py`)用同一套邏輯抓連續同號的天數/週數:

- `dealer_streak`:大盤自營商(自行買賣)最近 N 日的買賣方向,連續 5 日以上同向視為強烈訊號——選擇自營商自行買賣是因為它反映了自營商真正的方向性部位(相對於避險部位)。
- `holder_pct_streak`:觀察名單個股千張大戶佔集保庫存比例最近 N 週的週對週增減,連續 3 週以上同向時提示——連續下降常被視為大戶(聰明錢)派發的領先訊號,連續上升則反映籌碼持續集中。

### 6. 低頻資料(月營收/財報)每次執行都會打,但常常拿到重複資料;資產負債表則會先查資料庫再決定要不要打

`monthly_revenue.py`(月營收)與 `financial_income.py`(財報毛利率)背後的 TWSE OpenAPI 端點沒有回溯查詢,永遠只回傳「目前最新一期」,而且月營收/財報依法只在特定期間公告。這兩個 provider 的 `fetch()` 不做日期判斷,每次執行都會照打——大部分日子只是把同一期資料原樣 upsert 一次(靠 `pk` 冪等,不會產生重複列),但一旦新一期資料公告,下一次執行就能立刻抓到,不用等到特定月份/日期區間才有機會更新。

`balance_sheet.py`(資產負債表)背後的端點屬於同一個 TWSE OpenAPI 家族,一樣沒有回溯查詢、永遠只回傳最新一期,但多加了一層判斷:依台灣財報法定申報截止日(Q1 5/15、H1(Q2) 8/14、Q3 11/14、年報(Q4) 次年 3/31)反推「今天理論上最新一期應該是哪一期」,先用獨立唯讀連線查資料庫是否已有觀察名單這一期的資料——有就直接回傳既有資料、不打 API,沒有才真的送出請求。這個推算是用截止日曆估計,不是 100% 精確(個別公司偶爾會延遲公告一兩天),但足以把「每天都打一次卻幾乎每次都拿到同一份資料」的浪費降到最低。

財報(綜合損益表、資產負債表)目前都只涵蓋一般業公司(觀察名單標的皆屬此類),金融、證券期貨、保險、金控業的財報格式不同,暫不支援。

### 7. PE 河流圖是自建的,不是抓來的

TWSE 沒有歷史 PE 河流圖或百分位 API,`core/analysis.py` 的 `pe_river()` 純粹用這支程式自己每天累積在 `stock_quote` 表裡的 PE 資料算出目前 PE 的歷史百分位與極值。這代表功能剛裝好時樣本量幾乎是 0,要嘛讓程式每天正常執行慢慢累積,要嘛跑一次 `scripts/backfill_pe_history.py` 一次性回補過去幾年的每日 PE。JSON 裡的 `pe_river.note` 會依樣本天數附上警語(少於 60 天時明講百分位不具參考意義),避免把統計雜訊當成訊號。

### 8. 產業平均 PE 刻意沒有做

早期版本曾經把觀察名單裡同產業的股票互相取 PE 平均(標示 `scope: "watchlist_only"`),後來拿掉了:觀察名單每個產業通常只有 2~3 檔標的,樣本數小到不具統計意義,直接拿極小樣本平均去判斷個股「相對同業低估/高估」反而容易誤判(例如把單一權值股的 PE 拿去跟一兩檔小型股平均比較,結論會失真)。真正有意義的產業平均需要全市場同產業成分股 + 市值加權,目前沒有這個資料源,所以明確列在 `data_quality.unavailable` 說明原因,不用小樣本數字冒充有參考價值的指標(原則同第 3 點「寧缺勿濫」)。

### 9. 三個籌碼/總經資料源各自的怪癖

- **`holder_distribution.py`(集保股權分散表)**:TDCC 的憑證鏈掛在 `TWCA Global Root CA` 下,Python 內建(certifi)信任庫嚴格驗證會因缺少 Subject Key Identifier 而丟出 `SSLCertVerificationError`——這條鏈其實是作業系統信任庫認可的合法憑證(curl 用系統原生驗證就不會出錯),所以這支 provider 改用 [`truststore`](https://pypi.org/project/truststore/) 套件讓 Python 改走作業系統信任庫驗證,而不是關掉驗證(`verify=False`)。另外這支 API 每週才更新一次(以週五庫存為基準),沒有日期參數,永遠拿「最新一週」的資料,處理方式比照 `foreign_futures_oi.py`(見上方原理第 4 點)。
- **`ir_conference.py`(法說會日期)**:官方網域 `mops.twse.com.tw` 對雲端/機房 IP 常直接觸發 WAF 擋下(已實測驗證,回應「因為安全性考量」錯誤頁,無論帶什麼 Header 都一樣),改走鏡像網域 `mopsov.twse.com.tw` 可正常查詢到一致的資料。這支查詢是「依公司代號 + 民國年」查歷年法說會列表,不是「當天」資料;只查當年度,跨年度已公告的場次要等年度切換後才查得到;目前只用 `TYPEK=sii`(上市)查詢,觀察名單若有上櫃個股不會查到資料,ETF(如 0050)本身不開法說會、查無資料是正常現象不是抓取失敗。
- **`market_vix.py`(VIX 恐慌指數)**:資料來自 FRED(聖路易 Fed)的 `VIXCLS` 序列,需自行到 [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys) 免費申請 `FRED_API_KEY` 並寫入 `.env`,未設定則印警告並略過,不中斷主流程(做法比照寄信設定)。這是目前唯一用到的總經指標,主要用來支援「VIX>35 極端恐慌」這類條件單訊號。

### 10. 交易日曆:把「休市」跟「抓取失敗」分開

早期版本沒有交易日曆,`market_closed` 只能含糊地列在 `data_quality.unavailable` 說明「當天沒資料可能是休市也可能是抓取失敗,無法區分」。現在 `core/calendar.py` 的 `is_trading_day(date_str)` 會先查 TWSE 官方休市日期公告(`/v1/holidaySchedule/holidaySchedule`),回傳三態:

- 週六、週日不用查 API 就直接判定為休市。
- 平日先查臺北市天然災害停止上班公告(見下方),有確定停班就直接判定休市。
- 否則對照 TWSE 公告的年度休市日清單(國定假日、補假、僅辦理結算交割等)。這份清單裡有兩種容易混淆的項目:「農曆春節前最後交易日」「XX 後開始交易日」只是提醒性質的標記,當天市場正常交易,不是休市日——判斷時會用 `Name` 是否含「交易日」三字排除掉這兩種,避免誤判。
- 若年度休市日曆抓取失敗,或請求的日期超出「TWSE 目前已公告」的年度範圍(這支 API 沒有年度參數,通常只回傳當年度,約當年 Q4 起才會加上次年度),則回傳 `None` 代表「現在無法判斷」,呼叫端(`export_json.py`)會照實列在 `data_quality.unavailable`,不會亂猜。

`main.py` 執行時會先印出當天是否為休市日;`export_json.py` 則會在 JSON 頂層明確寫出 `market_closed: true/false`(可判斷時)。之所以選 TWSE 官方公告而不是第三方交易日曆套件(例如 `pandas_market_calendars`),是因為前者是這支程式其他 provider 本來就在用的同一個官方 API 家族,不用多引入 `pandas` 這類重量級相依套件,而且官方公告本身就是最新、最權威的來源。

**颱風假(天然災害停止上班)**:年度休市日曆是預先排定的,沒辦法預先收錄臨時性的颱風假。`_load_typhoon_closures()` 改抓行政院人事行政總處「天然災害停止上班及上課情形」CAP 告警 Atom feed([data.gov.tw/dataset/20457](https://data.gov.tw/dataset/20457),`https://alerts.ncdr.nat.gov.tw/RssAtomFeed.ashx?AlertType=33`),平時是空的,只有天然災害發生時才有內容,不用額外控制 polling 頻率(反正一天只執行一次)。只認**臺北市**的停班公告——證交所實務上是跟公司所在地臺北市政府的決定走,其他縣市單獨停班不影響台股交易;而且只採信摘要文字裡明確寫「停止上班」的確定公告,排除「已達停止上班及上課標準」這種預告性質、可能還會變動的用語,也只解析摘要裡明確寫出的「M/D」日期,「今天/明天」這類相對日期描述目前不解析(寧可漏判,不要因為解析錯日期而錯殺一個正常交易日)。這支 feed 本身抓取失敗不會影響年度休市日曆的判斷結果,只是這次執行看不到颱風假而已。

### 11. 執行流程

```text
main.py run()
  ├─ is_trading_day(date_str)  印出當天是否為休市日(交易日曆,見上方原理第 10 點)
  ├─ 逐一走訪 load_providers() 回傳的每個 provider
  │    ├─ ensure_table()  若表不存在則建立
  │    ├─ fetch(date_str) 呼叫外部 API 拿當日資料
  │    ├─ upsert()        寫入 SQLite(冪等)
  │    └─ sleep(SLEEP_SEC) 禮貌性間隔,避免打爆對方 API
  ├─ dealer_streak()      判斷自營商連續方向,印出主控台提示
  ├─ VIX>35 檢查           印出主控台提示(需先設定 FRED_API_KEY 才會有資料)
  ├─ revenue_streak()     判斷個股月營收 YoY 連續成長/衰退 ≥3 個月,印出主控台提示
  ├─ pe_river()           判斷個股 PE 落在自建歷史的極端百分位(≤10 或 ≥90),印出主控台提示
  ├─ holder_pct_streak()  判斷個股千張大戶佔比連續增/減 ≥3 週,印出主控台提示
  ├─ export_excel()       整庫匯出成 Excel,一表一分頁
  ├─ export_weekly_scan() 整庫組成正規化 JSON
  └─ send_report()        寄出 Excel + JSON(未設定信箱則略過;寄信失敗只印警告,不中斷 run)
```

> `margin_balance.py`(個股融資融券)與 `market_margin.py`(全市場融資融券)其實是同一支 TWSE `MI_MARGN` API 回應裡的兩張表(`tables[1]` 個股明細、`tables[0]` 全市場彙總),兩個 provider 透過 `providers/_mi_margn.py` 共用同一次請求的快取結果,同一天只會真的打一次 API,不會因為拆成兩個 provider 就發送兩次重複請求。

## 安裝

### 1. 需求

- Python 3.9 以上(開發環境為 3.14)
- 一組 Gmail 帳號 + 應用程式密碼(僅寄信功能需要,非必要)
- 一組免費 FRED API Key(僅 VIX 抓取需要,非必要)
- 需能連線到以下網域:`www.twse.com.tw`、`openapi.twse.com.tw`、`openapi.taifex.com.tw`、`opendata.tdcc.com.tw`、`mopsov.twse.com.tw`、`api.stlouisfed.org`——公司/機房網路若有白名單限制或代理伺服器,請先確認這些網域可連通,否則對應 provider 會抓取失敗並印警告(不會中斷其他 provider)

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

### 5. (選用)設定寄信功能與 VIX

在專案根目錄建立 `.env`(此檔案已列入 `.gitignore`,不會進版控):

```env
SENDER_EMAIL=you@gmail.com
SENDER_APP_PASSWORD=xxxx-xxxx-xxxx-xxxx
EMAIL_TO=receiver@example.com
FRED_API_KEY=your_fred_api_key
```

`SENDER_APP_PASSWORD` 是 Gmail 的「應用程式密碼」,不是登入密碼,需先在 Google 帳戶開啟兩步驟驗證後才能產生:[myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords)。`EMAIL_TO` 是報表收件地址。`SENDER_EMAIL`/`SENDER_APP_PASSWORD`/`EMAIL_TO` 三個變數任一未設定,程式會自動略過寄信,不影響抓取與匯出報表。

`FRED_API_KEY` 是 `market_vix.py`(VIX 恐慌指數)需要的免費金鑰,在 [fredaccount.stlouisfed.org/apikeys](https://fredaccount.stlouisfed.org/apikeys) 註冊即可取得,未設定則自動略過 VIX 抓取,不影響其他資料源。

## 使用

### 基本執行

```bash
python main.py            # 抓今天
python main.py 20260713   # 抓指定日期(格式 YYYYMMDD)
```

### 執行時會發生什麼

1. 依 TWSE 官方休市公告判斷今天是否為交易日,印出提示(見上方「原理」第 10 點)
2. 掃描 `providers/` 下所有資料源,逐一抓取當日資料並 upsert 進 `data/chip.db`,主控台會印出每個 provider 的抓取結果(月營收/財報每次都會呼叫 API,但常拿到與前次相同的最新一期資料,見上方「原理」第 6 點;集保股權分散表每週才會有新資料,見「原理」第 9 點)
3. 印出自營商近 6 日買賣方向,連續同向達 5 日以上會提示強烈訊號
4. 若 VIX > 35 印出極端恐慌提示(需先設定 `FRED_API_KEY`)
5. 印出觀察名單個股月營收 YoY 連續成長/衰退達 3 個月以上的提示
6. 印出觀察名單個股 PE 落在自建歷史極端百分位(≤10 或 ≥90,且樣本 ≥60 天)的提示
7. 印出觀察名單個股千張大戶佔比連續增/減達 3 週以上的提示
8. 匯出 `data/chip_report_YYYYMMDD.xlsx`
9. 匯出 `data/weekly_scan_YYYYMMDD.json`
10. 寄出報表(Excel + JSON 附件)至 `.env` 裡設定的 `EMAIL_TO`(需先完成上方「設定寄信功能」步驟)

`data/` 底下的輸出檔案(資料庫、Excel、JSON)不會進 git(已列入 `.gitignore`),每台機器/每次 clone 都是從零開始累積歷史。

### PE 河流圖歷史回補(選用,建議跑一次)

`pe_river` 統計(見上方「原理」第 7 點)靠每天累積的 PE 資料才有意義,剛裝好時樣本幾乎是 0。可以跑一次性回補腳本,把過去幾年的每日 PE 補進資料庫:

```bash
python scripts/backfill_pe_history.py            # 回補近 3 年(預設)
python scripts/backfill_pe_history.py --years 5  # 回補近 5 年
```

這支腳本會逐一交易日呼叫 TWSE 每日收盤價 API(平日才嘗試,週末自動跳過),依 `config.SLEEP_SEC` 節流,回補 3 年約需數百次請求、數十分鐘。只需跑一次,之後 `main.py` 每天正常執行就會持續累積,不用重跑(除非要拉長回補範圍)。

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
| `foreign_futures_oi.py` | `foreign_futures_oi` | 三大法人(外資及陸資/投信/自營商)期貨未平倉,可比對土洋對作(僅回傳最新交易日) | TAIFEX OpenAPI |
| `stock_inst.py` | `stock_chip` | 觀察名單個股三大法人買賣超 | TWSE T86 |
| `margin_balance.py` | `margin_balance` | 觀察名單個股融資融券餘額 | TWSE MI_MARGN |
| `sbl_balance.py` | `sbl_balance` | 觀察名單個股借券賣出餘額與當日賣出/還券增減 | TWSE TWT93U |
| `stock_quote.py` | `stock_quote` | 觀察名單個股收盤價/本益比/股價淨值比 | TWSE BWIBBU_d |
| `stock_price_action.py` | `stock_price_action` | 觀察名單個股開高低收、單日漲跌點數/幅度、成交量/成交金額 | TWSE MI_INDEX(type=ALLBUT0999) |
| `monthly_revenue.py` | `monthly_revenue` | 觀察名單個股月營收、YoY/MoM 增減幅、產業別 | TWSE OpenAPI t187ap05_L |
| `financial_income.py` | `financial_income` | 觀察名單個股(一般業)毛利率/營益率/淨利率/EPS | TWSE OpenAPI t187ap06_L_ci |
| `balance_sheet.py` | `balance_sheet` | 觀察名單個股(一般業)資產/負債/權益總額、負債比率、每股參考淨值 | TWSE OpenAPI t187ap07_L_ci |
| `holder_distribution.py` | `holder_distribution` | 觀察名單個股集保股權分散表:千張大戶(持股≥1,000張)人數/佔集保庫存比例,週更 | TDCC OpenData(id=1-5) |
| `market_vix.py` | `market_vix` | VIX 恐慌指數,用於總經條件單(如 VIX>35 極端恐慌);需自行申請 `FRED_API_KEY` | FRED(St. Louis Fed)VIXCLS |
| `ir_conference.py` | `ir_conference` | 觀察名單個股法人說明會(法說會)日期、時間、地點、擇要訊息 | MOPS t100sb02_1 |

### 自行衍生的指標(非官方 API 直接提供)

這些指標官方沒有現成端點,由 `core/analysis.py` 用上述資料表自行計算,只在有足夠樣本時才輸出,不足時明確列在 JSON 的 `data_quality.unavailable`:

| 指標 | 計算方式 | 限制 |
| --- | --- | --- |
| 營收 YoY 連續成長/衰退月數 | 累積 `monthly_revenue` 歷史,逐月比對 YoY 正負號 | 需要跑過夠多個月才有意義 |
| PE 河流圖(百分位/極值) | 累積 `stock_quote.pe` 歷史,算目前 PE 在自己歷史分布的排名 | 自建,非官方河流圖;可用 `scripts/backfill_pe_history.py` 回補加速 |
| 千張大戶佔比連續增/減週數 | 累積 `holder_distribution` 週資料,逐週比對佔比增減方向 | 週更資料,需要跑過夠多週才有意義;連續下降常被視為大戶(聰明錢)派發的領先訊號 |

## 設定

編輯 `config.py`:

- `WATCHLIST`:觀察名單(股票代號 → 名稱),個股相關 provider 只抓這裡列出的標的
- `DB_PATH` / `EXCEL_PATH` / `JSON_PATH`:輸出檔案路徑(實際匯出檔名會自動加上日期後綴)
- `SLEEP_SEC`:每個 provider 抓取後的間隔秒數,避免對 API 過於頻繁請求;`ir_conference.py` 對觀察名單逐檔查詢時,每檔之間也是用這個秒數節流

收件地址 `EMAIL_TO` 與 `FRED_API_KEY` 不在 `config.py` 裡,而是放在 `.env`(見上方「設定寄信功能與 VIX」),避免個人信箱與金鑰進版控。

## 架構

```text
main.py               進入點:載入 provider → 抓取 → 存 DB → 分析 → 匯出報表
config.py             觀察名單與路徑設定
core/
  base.py             DataProvider 抽象基底類別
  registry.py         自動掃描 providers/ 底下的模組並實例化
  storage.py          SQLite 存取(建表、upsert、schema 變更時自動搬遷舊資料)
  analysis.py         籌碼分析(自營商連續方向、營收動能連續月數、PE河流圖百分位、千張大戶佔比連續週數)
  calendar.py         交易日曆(is_trading_day):依 TWSE 官方休市公告 + 臺北市天然災害停班公告判斷是否為交易日
  report.py           匯出 Excel
  export_json.py      組出給 AI 判讀用的正規化 JSON
  mailer.py           寄送報表(Gmail SMTP,讀取 .env 帳密)
providers/            各資料源實作,每個檔案對應一個 DataProvider 子類別
  _mi_margn.py        內部共用模組(非 DataProvider):margin_balance/market_margin 共用的 MI_MARGN 請求快取
scripts/
  backfill_pe_history.py  一次性回補觀察名單個股歷史 PE,加速 PE 河流圖累積樣本
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
