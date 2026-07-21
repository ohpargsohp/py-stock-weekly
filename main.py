import os
import sys
import time
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設 cp950,印中文/emoji 會炸

from dotenv import load_dotenv

load_dotenv()

import config
from core.analysis import dealer_streak, holder_pct_streak, pe_river, revenue_streak
from core.calendar import is_trading_day
from core.export_json import export_weekly_scan
from core.mailer import send_report
from core.registry import load_providers
from core.report import export_excel
from core.storage import Storage


def _with_date(path, date_str):
    root, ext = os.path.splitext(path)
    return f"{root}_{date_str}{ext}"


def run(date_str=None):
    date_str = date_str or datetime.now().strftime("%Y%m%d")

    trading_day = is_trading_day(date_str)
    if trading_day is False:
        print(f"📅 {date_str} 為 TWSE 官方公告休市日(週末或國定假日),當天各資料源預期不會有新資料")
    elif trading_day is None:
        print(f"📅 {date_str} 是否為交易日目前無法判斷(交易日曆抓取失敗或不涵蓋此年度)")

    store = Storage(config.DB_PATH)

    for p in load_providers():
        store.ensure_table(p)
        rows = p.fetch(date_str)
        store.upsert(p, rows)
        msg = p.describe(rows)
        print(msg if msg else f"✅ {p.name}: {len(rows)} 筆")
        time.sleep(config.SLEEP_SEC)

    streak = dealer_streak(store.conn, 6)
    if streak:
        signs = ["買" if v > 0 else "賣" for _, v in streak]
        print(f"\n🆕 自營商(自行買賣)近{len(signs)}日:{' '.join(signs)}")
        if len(set(signs)) == 1 and len(signs) >= 5:
            print(f"⚠️ 連{len(signs)}日同向{signs[0]}超 = 強烈訊號")

    vix_row = store.conn.execute(
        "SELECT trade_date, vix FROM market_vix ORDER BY trade_date DESC LIMIT 1"
    ).fetchone()
    if vix_row and vix_row[1] > 35:
        print(f"🚨 VIX {vix_row[1]:.2f} > 35,市場極度恐慌")

    for sid, name in config.WATCHLIST.items():
        rev_rows = revenue_streak(store.conn, sid, 6)
        if rev_rows:
            signs = ["正" if v > 0 else "負" for _, v in rev_rows]
            months = 1
            for s in signs[1:]:
                if s != signs[0]:
                    break
                months += 1
            if months >= 3:
                print(f"📈 {name}({sid}) 月營收YoY連續{months}個月{signs[0]}成長")

        river = pe_river(store.conn, sid)
        if river and river["sample_days"] >= 60:
            pct = river["percentile"]
            if pct <= 10 or pct >= 90:
                zone = "低檔" if pct <= 10 else "高檔"
                print(f"📊 {name}({sid}) PE {river['current_pe']} 落在自建歷史第{pct}百分位"
                      f"({zone},樣本{river['sample_days']}天)")

        holder_streak = holder_pct_streak(store.conn, sid, 6)
        if holder_streak:
            signs = ["增" if v > 0 else "減" for _, v in holder_streak]
            weeks = 1
            for s in signs[1:]:
                if s != signs[0]:
                    break
                weeks += 1
            if weeks >= 3:
                print(f"👥 {name}({sid}) 千張大戶佔比連續{weeks}週{signs[0]}")

    store.close()

    excel_path = _with_date(config.EXCEL_PATH, date_str)
    export_excel(config.DB_PATH, excel_path)
    print(f"📊 報表已輸出: {excel_path}")

    json_path = _with_date(config.JSON_PATH, date_str)
    export_weekly_scan(config.DB_PATH, json_path, date_str)
    print(f"🧾 判讀用 JSON 已輸出: {json_path}")

    try:
        send_report([json_path, excel_path])
    except Exception as e:
        print(f"⚠️ 寄信失敗,但資料已正確寫入 {excel_path} / {json_path}:{e}")


if __name__ == "__main__":
    # 用法:python main.py            → 抓今天
    #       python main.py 20260713   → 抓指定日
    run(sys.argv[1] if len(sys.argv) > 1 else None)
