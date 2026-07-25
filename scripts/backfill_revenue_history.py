"""IMP-4:一次性回補觀察名單個股的歷史月營收,讓 core/analysis.py 的
revenue_streak()「YoY 連續成長/衰退月數」一開始就有真正的歷史月數可用。

providers/monthly_revenue.py 背後的 TWSE OpenAPI(t187ap05_L)端點沒有回溯查詢
能力,每次呼叫永遠只回傳「目前最新一期」(見 ARCHITECTURE.md 原理第 6 點),
無法拿來回補歷史,所以這支腳本改用 MOPS「上市公司每月營業收入彙總表」的
歷史靜態頁面(t21sc03,格式已實測驗證:網址是民國年+月組成,月份不補零,
例如 2026 年 6 月是 .../t21sc03_115_6.html,不是 _115_06.html;至少回溯至
民國 105 年(2016)仍能正常取得)。這份頁面涵蓋全體上市公司,依產業別分段,
回補時只取 config.WATCHLIST 內的個股;沒有月營收公告的 ETF(如 0050)本來
就不會出現在頁面裡,是正常現象。

這份靜態頁面不像 t187ap05_L 有「出表日期」欄位,回補的資料列 report_date
留白(None)——這個欄位目前沒有被 core/analysis.py 或 core/export_json.py
用到,不影響任何判斷邏輯;industry(產業別)欄位也留白,同樣理由,不強行
解析頁面裡跟表頭黏在一起的產業別文字徒增出錯風險。

日常 main.py 照常每天執行 monthly_revenue provider,新一期公告後會自動累積,
不需要重跑這支腳本(除非要拉長回補範圍)。

用法:
    python scripts/backfill_revenue_history.py                 # 回補到 202401(預設)
    python scripts/backfill_revenue_history.py --start 202301  # 自訂起始年月(YYYYMM)
"""
import argparse
import os
import sys
import time
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import requests
from bs4 import BeautifulSoup

import config
from core.storage import Storage
from providers.monthly_revenue import MonthlyRevenueProvider

HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num_or_none(s):
    s = s.strip().replace(",", "")
    if s in ("", "-"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _periods_from(start_period):
    """'202401' -> 逐月產生到「上個月」為止的 'YYYYMM' 字串(本月交給日常
    main.py 的即時 provider 處理,這支腳本只管已經走完、公告應已底定的月份)。"""
    now = datetime.now()
    year, month = int(start_period[:4]), int(start_period[4:])
    periods = []
    while (year, month) < (now.year, now.month):
        periods.append(f"{year:04d}{month:02d}")
        month += 1
        if month > 12:
            month = 1
            year += 1
    return periods


def fetch_month(period):
    """period 是 'YYYYMM',回傳該月觀察名單個股的月營收 list[dict](schema 比照
    MonthlyRevenueProvider),取不到(該月頁面不存在、格式跟預期不符)回傳 []。"""
    year, month = int(period[:4]), int(period[4:])
    roc_year = year - 1911
    url = f"https://mopsov.twse.com.tw/nas/t21/sii/t21sc03_{roc_year}_{month}.html"
    try:
        r = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"⚠️ {period} 抓取失敗: {e}")
        return []
    if r.status_code != 200:
        return []
    r.encoding = "cp950"

    soup = BeautifulSoup(r.text, "lxml")
    tables = soup.find_all("table")
    if not tables:
        return []

    out = []
    for row in tables[0].find_all("tr"):
        cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
        if len(cells) < 10 or cells[0] not in config.WATCHLIST:
            continue
        out.append({
            "period": period,
            "stock_id": cells[0],
            "stock_name": config.WATCHLIST[cells[0]],
            "industry": None,
            "revenue": _to_num_or_none(cells[2]),
            "revenue_prev_month": _to_num_or_none(cells[3]),
            "revenue_last_year_month": _to_num_or_none(cells[4]),
            "revenue_mom_pct": _to_num_or_none(cells[5]),
            "revenue_yoy_pct": _to_num_or_none(cells[6]),
            "report_date": None,
        })
    return out


def backfill(start_period="202401", sleep_sec=None):
    sleep_sec = config.SLEEP_SEC if sleep_sec is None else sleep_sec
    store = Storage(config.DB_PATH)
    provider = MonthlyRevenueProvider()
    store.ensure_table(provider)

    periods = _periods_from(start_period)
    fetched, skipped = 0, 0
    for period in periods:
        rows = fetch_month(period)
        if rows:
            store.upsert(provider, rows)
            fetched += 1
            print(f"   ...{period} 回補 {len(rows)} 檔")
        else:
            skipped += 1
            print(f"   ...{period} 無資料(頁面不存在或格式不符,略過)")
        time.sleep(sleep_sec)

    store.close()
    print(f"✅ 月營收歷史回補完成:共 {len(periods)} 個月,成功 {fetched} 個月,"
          f"略過 {skipped} 個月")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", default="202401", help="回補起始年月 YYYYMM(預設 202401)")
    args = parser.parse_args()
    backfill(start_period=args.start)
