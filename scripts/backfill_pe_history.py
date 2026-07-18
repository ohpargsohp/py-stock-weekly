"""一次性回補觀察名單個股的歷史 PE(股價/本益比/淨值比),讓
core/analysis.py 的 pe_river()「自建河流圖」一開始就有足夠樣本可用。

日常 main.py 只會累積「今天」這一筆,要讓河流圖有意義得先跑一次這支腳本,
把過去 N 年的每個交易日補進 stock_quote 表。之後 main.py 照常每天執行,
歷史會持續累積,不需要重跑這支腳本(除非要拉長回補範圍)。

用法:
    python scripts/backfill_pe_history.py            # 回補近 3 年
    python scripts/backfill_pe_history.py --years 5  # 回補近 5 年
"""
import argparse
import os
import sys
import time
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

import config
from core.storage import Storage
from providers.stock_quote import StockQuoteProvider


def backfill(years=3, sleep_sec=None):
    sleep_sec = config.SLEEP_SEC if sleep_sec is None else sleep_sec
    store = Storage(config.DB_PATH)
    provider = StockQuoteProvider()
    store.ensure_table(provider)

    end = datetime.now()
    start = end - timedelta(days=365 * years)
    total_days = (end - start).days + 1

    fetched, skipped = 0, 0
    d = start
    while d <= end:
        if d.weekday() < 5:  # 只嘗試平日,週末必為休市不浪費請求
            date_str = d.strftime("%Y%m%d")
            try:
                rows = provider.fetch(date_str)
            except Exception as e:
                print(f"⚠️ {date_str} 抓取失敗: {e}")
                rows = []
            if rows:
                store.upsert(provider, rows)
                fetched += 1
                if fetched % 20 == 0:
                    print(f"   ...已回補 {fetched} 個交易日(最新處理: {date_str})")
            else:
                skipped += 1
            time.sleep(sleep_sec)
        d += timedelta(days=1)

    store.close()
    print(f"✅ PE 歷史回補完成:共嘗試 {total_days} 天(平日),"
          f"成功 {fetched} 個交易日,無資料(休市/失敗) {skipped} 天")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--years", type=int, default=3, help="回補幾年歷史(預設 3)")
    args = parser.parse_args()
    backfill(years=args.years)
