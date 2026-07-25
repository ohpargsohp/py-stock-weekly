"""IMP-2 早盤定稿排程:次日 08:30 重跑「前一交易日」的 JSON,補齊晚間 20:00
產出時還缺的 T+1 資料(TAIFEX 期貨未平倉、FRED VIX 都只給前一交易日的收盤資料)。

前一交易日用 core/calendar.py 的交易日曆推算(而非單純減一天),
週一執行時會正確回補「上週五」而非「週日」;遇到年度休市日曆無法判斷的情況
會直接跳過,不亂猜日期。

重跑後 JSON 的 revision 會自動變成 "final"(core/export_json.py 用「執行當下的
實際日期」晚於這份報告的 as_of 來判斷,不需要在這裡手動傳旗標)。

用法:
    python scripts/run_morning.py
"""
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv

load_dotenv()

from core.calendar import previous_trading_day
from main import run


def run_morning():
    today_str = datetime.now().strftime("%Y%m%d")
    target = previous_trading_day(today_str)
    if target is None:
        print(f"⚠️ 無法判斷 {today_str} 的前一交易日(交易日曆無法判斷),本次早盤定稿跳過")
        return
    print(f"🌅 早盤定稿:重跑 {target} 的 JSON")
    run(target)


if __name__ == "__main__":
    run_morning()
