# 架構與設計原理

補充 [py-stock-weekly](README.md) 內部的設計邏輯、各資料源的細節限制,以及如何擴充新資料源。基本安裝與使用方式請見 [README.md](README.md)。

## 目錄

- [原理](#原理)
- [資料來源](#資料來源)
- [專案結構](#專案結構)
- [新增資料源](#新增資料源)

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

各區塊自己標出落後的日期還不夠——AI 判讀方看到「兩個不同日期」不見得會意識到「這是過期資料,不能當今天的訊號解讀」。`data_quality.stale`(見 `_add_stale()`)把這件事量化:對 `market_vix`、`market_margin`、`foreign_futures_oi`,以及 watchlist 內層的 `sbl_balance`、`holder_distribution`,逐一拿它們自己的日期跟 `as_of` 比對,算出 `lag_days`(見下一點,用交易日曆算,不是日曆天數)、附上已知的落後原因(如 `"TAIFEX T+1 公布"`、`"TDCC 週更"`),同一個欄位只記一次。`stale` 陣列永遠存在(即使是空陣列),代表「這次有檢查過,沒有落後」,跟陣列裡沒有這個欄位是兩種不同的意思。

### 4b. 落後天數的計算:交易日曆,不是日曆天數

`core/calendar.py` 的 `trading_days_between(start, end)` 算「從 start(不含)到 end(含)之間有幾個交易日」,而不是單純日曆天數相減——週五的資料在週一被讀取時,`lag_days` 應該是 1(只隔了 1 個交易日),不是 3(週六日週一的日曆天數)。做法是逐一日曆日呼叫 `is_trading_day()` 累加,`is_trading_day()` 回傳 `None`(無法判斷)的日子保守地不計入,寧可低估落後天數也不要因為交易日曆本身不確定而誤判。同一支模組另外提供 `previous_trading_day(date_str)`,回傳前一個交易日(不是單純減一天),支援下面第 13 點的雙排程機制。

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

### 12. 雙排程:晚間 draft、早盤 final,revision 不是手動旗標

台股收盤後(20:00)第一次執行時,TAIFEX 期貨未平倉、FRED VIX 常常還沒更新到當天(它們本身就是 T+1 公布,見第 4 點),這時輸出的 JSON 只能算「草稿」。次日開盤前(08:30)可以再重跑同一天的 JSON,這時 T+1 資料通常已經齊了,可以視為「定稿」。

`revision`(`"draft"` / `"final"`)這個欄位**不是**呼叫端手動傳的旗標,而是 `build_weekly_scan()` 自己拿「執行當下的實際日期」跟這份報告的 `as_of` 比較算出來的:執行日等於 `as_of` 當天 → `draft`;執行日晚於 `as_of` → `final`。這樣設計是因為手動旗標很容易忘記傳、或傳錯——不管是排程按表操作、還是事後手動補跑某一天的資料,只要「現在」已經過了那個交易日,T+1 資料照理說都應該公布完整了,標成 `final`就是對的,不需要呼叫端自己判斷「這是不是早盤那次執行」。

早盤這次重跑由 `scripts/run_morning.py` 負責:用 `core/calendar.py` 的 `previous_trading_day(today)` 算出「前一個交易日」(不是單純減一天——週一執行時會正確算回上週五,而不是週日),呼叫 `main.run(前一交易日)`。`run_daily.bat`(晚間)、`run_morning.bat`(早盤)是兩支各自獨立的 Windows 排程進入點,分別掛到工作排程器的 20:00 與 08:30。兩次都是對同一天的資料重跑,冪等寫入保證不會弄髒資料庫,`revision` 欄位讓 AI 判讀方知道現在看到的是哪個階段的資料。

### 13. 連續趨勢訊號的歷史不足防護

`revenue_streak()`(月營收 YoY 連續成長/衰退)與 `holder_pct_streak()`(千張大戶佔比連續增減)這兩個「連續同向」指標有一個共同的陷阱:資料庫剛開始累積、只有 1~2 期歷史時,streak 「必然」等於現有的期數本身——不是因為真的連續這麼多期同向,只是因為沒有更早的資料可以推翻它。這種情況下輸出的數字看起來跟正常訊號一模一樣,但其實是「資料不足」被誤標成「有效訊號」,是目前 JSON 裡少數會輸出「錯誤數字」而非「明確缺項」的地方,違反第 3 點「寧缺勿濫」的原則。

`export_json.py` 因此在組出 `watchlist[].revenue_momentum` 跟 `watchlist[].holder_distribution` 前,先用 `core/analysis.py` 的 `revenue_history_count()` / `holder_history_count()` 查該檔股票目前實際累積了幾期(而不是只看 streak 本身算出來的長度)。低於門檻(`MIN_HISTORY_MONTHS` / `MIN_HISTORY_WEEKS`,目前都是 6)時,`yoy_streak_months`/`streak_weeks` 與對應的 `_direction` 直接輸出 `null`,改附上 `streak_note: "history_insufficient(現有期數/門檻)"`,讓 AI 判讀方看到 `null` + 註記就知道該忽略這個訊號,而不是誤把「資料不足導致的巧合」當成「連續趨勢」引用。門檻只擋輸出,不影響底層資料照常一天/一週一筆累積——跑過夠久之後,streak 自然會開始輸出真實數字。

### 14. 月營收歷史回補:t187ap05_L 沒有回溯查詢,改用 MOPS 靜態彙總頁面

第 13 點的防護只是「不要輸出錯誤數字」,治標不治本——真正解法是讓 `monthly_revenue` 表有夠長的歷史可用。但日常執行的 `providers/monthly_revenue.py` 打的是 TWSE OpenAPI `t187ap05_L`,這個端點**沒有回溯查詢能力**,不管哪天呼叫永遠只回傳「目前最新一期」(已實測驗證:1082 筆全上市公司資料,`資料年月` 全部是同一期),沒有年月參數可以指定過去某個月,無法拿來回補歷史。

`scripts/backfill_revenue_history.py` 改用 MOPS「上市公司每月營業收入彙總表」的歷史靜態頁面(`https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_{民國年}_{月}.html`,月份**不補零**——6 月是 `t21sc03_115_6.html` 而不是 `_115_06.html`,已實測驗證至少可回溯到民國 105 年)。這份頁面涵蓋全體上市公司、依產業別分段,回補時只取 `config.WATCHLIST` 內的個股,ETF(如 0050)本來就沒有月營收公告,不會出現在頁面裡是正常現象。

解析上有一個容易踩的坑:這份頁面的 HTML 結構不太乾淨,用 `BeautifulSoup(html, "html.parser")` 解析時,表格第一列會把後面所有列的內容全部錯誤地巢狀合併進同一個 `<tr>`(變成一列上千個 `<td>`),必須改用 `BeautifulSoup(html, "lxml")` 才能正確拆成一列一間公司。用 `lxml` 之後,個股資料列仍然可以直接靠「第一格是不是 `config.WATCHLIST` 裡的股票代號」正確篩選出來,不受那個畸形的合併列干擾(合併列自己的第一格是「產業別:...」文字,不會誤命中)。

這份靜態頁面沒有 `t187ap05_L` 才有的「出表日期」欄位,回補的資料列 `report_date` 留白;頁面裡的產業別文字跟表頭黏在同一格,回補時 `industry` 也留白不強行解析——這兩個欄位目前都沒有被 `core/analysis.py` 或 `core/export_json.py` 用到,留白不影響任何判斷邏輯。回補只需跑一次(`python scripts/backfill_revenue_history.py`,預設回補到 2024 年 1 月;`--start YYYYMM` 可自訂起點),之後 `main.py` 每天正常執行,新一期公告後 `monthly_revenue.py` 會自動接著累積,不需要重跑。

### 15. PE 河流圖的分母標註:財報季會讓百分位跳點,不是市場重估

`pe_river()`(第 7 點)算的是目前 PE 落在歷史分布的第幾百分位,但 PE 的分母(trailing EPS)不是連續變化的——依台灣財報法定申報截止日(Q1 5/15、H1(Q2) 8/14、Q3 11/14、年報(Q4) 次年 3/31),每次新一季財報申報後,`stock_quote` 累積的歷史 PE 樣本雖然不變,但「目前 PE 用的是哪一季 EPS」會換血,可能讓百分位在股價完全沒動的情況下大幅跳動(例如台積電 8 月 Q2 財報公布後,分母從 Q1 換成 Q2,PE 從 31.6 跳到約 28,百分位跟著驟降)。如果不特別標註,AI 判讀方容易把這種「分母換血造成的跳點」誤讀成「市場重新評價、股票變便宜了」。

`export_json.py` 因此在 `pe_river` 區塊額外帶上 `eps_basis`(固定是 `"trailing_4q_reported"`)、`latest_quarter_included`(直接沿用同一檔股票 `gross_margin.period`,即目前這組 PE 算的是哪一季財報的 EPS)、`next_rebase_expected`(依上述申報截止日反推下一次換血預期落在哪個月,例如 `2026Q1` → `2026-08`)。這三個欄位只是標註,不影響 `pe_river` 本身的計算方式;讀取方看到百分位大幅變動時,可以先比對 `next_rebase_expected` 是否剛好落在附近,判斷這是分母換血還是真的值得注意的市場重估。

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

這些指標官方沒有現成端點,由 `core/analysis.py` 用上述資料表自行計算,只在有足夠樣本時才輸出;PE 河流圖樣本不足時列在 JSON 的 `data_quality.unavailable`,兩個連續 streak 指標樣本不足時則輸出 `null` + `streak_note`(見原理第 13 點,理由是「資料不足」跟「查不到這個資料源」是不同性質的缺項):

| 指標 | 計算方式 | 限制 |
| --- | --- | --- |
| 營收 YoY 連續成長/衰退月數 | 累積 `monthly_revenue` 歷史,逐月比對 YoY 正負號 | 少於 `MIN_HISTORY_MONTHS`(6)個月時輸出 `null` + `streak_note`;可用 `scripts/backfill_revenue_history.py` 回補加速(見原理第 14 點) |
| PE 河流圖(百分位/極值) | 累積 `stock_quote.pe` 歷史,算目前 PE 在自己歷史分布的排名 | 自建,非官方河流圖;可用 `scripts/backfill_pe_history.py` 回補加速;另帶 `eps_basis`/`next_rebase_expected` 標註分母換血時機(見原理第 15 點) |
| 千張大戶佔比連續增/減週數 | 累積 `holder_distribution` 週資料,逐週比對佔比增減方向 | 少於 `MIN_HISTORY_WEEKS`(6)週時輸出 `null` + `streak_note`;連續下降常被視為大戶(聰明錢)派發的領先訊號 |

## 專案結構

```text
main.py               進入點:載入 provider → 抓取 → 存 DB → 分析 → 匯出報表
config.py             路徑等共用設定,從 watchlist.py 匯入 WATCHLIST 一併對外暴露(config.WATCHLIST)
watchlist.py          觀察名單(個人資料,已列入 .gitignore,不進版控;複製 watchlist.example.py 建立)
core/
  base.py             DataProvider 抽象基底類別
  registry.py         自動掃描 providers/ 底下的模組並實例化
  storage.py          SQLite 存取(建表、upsert、schema 變更時自動搬遷舊資料)
  analysis.py         籌碼分析(自營商連續方向、營收動能連續月數、PE河流圖百分位、千張大戶佔比連續週數)
  calendar.py         交易日曆:is_trading_day 依 TWSE 官方休市公告 + 臺北市天然災害停班公告判斷是否為交易日;
                      trading_days_between/previous_trading_day 用交易日曆算落後天數與前一交易日
  report.py           匯出 Excel
  export_json.py      組出給 AI 判讀用的正規化 JSON
  mailer.py           寄送報表(Gmail SMTP,讀取 .env 帳密)
providers/            各資料源實作,每個檔案對應一個 DataProvider 子類別
  _mi_margn.py        內部共用模組(非 DataProvider):margin_balance/market_margin 共用的 MI_MARGN 請求快取
scripts/
  backfill_pe_history.py       一次性回補觀察名單個股歷史 PE,加速 PE 河流圖累積樣本
  backfill_revenue_history.py  一次性回補觀察名單個股歷史月營收(見原理第 14 點),加速 YoY streak 累積樣本
  run_morning.py               早盤定稿排程(見原理第 12 點):算出前一交易日,重跑該日 JSON 讓 revision 變成 final
run_daily.bat / run_morning.bat  Windows 工作排程器進入點(晚間 20:00 / 早盤 08:30,見原理第 12 點)
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
