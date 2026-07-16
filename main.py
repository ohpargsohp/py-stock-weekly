import os
import sys
import time
from datetime import datetime

if sys.stdout.encoding and sys.stdout.encoding.lower() != "utf-8":
    sys.stdout.reconfigure(encoding="utf-8")  # Windows 主控台預設 cp950,印中文/emoji 會炸

from dotenv import load_dotenv

load_dotenv()

import config
from core.analysis import dealer_streak
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

    store.close()

    excel_path = _with_date(config.EXCEL_PATH, date_str)
    export_excel(config.DB_PATH, excel_path)
    print(f"📊 報表已輸出: {excel_path}")

    json_path = _with_date(config.JSON_PATH, date_str)
    export_weekly_scan(config.DB_PATH, json_path)
    print(f"🧾 判讀用 JSON 已輸出: {json_path}")

    try:
        send_report([json_path, excel_path])
    except Exception as e:
        print(f"⚠️ 寄信失敗,但資料已正確寫入 {excel_path} / {json_path}:{e}")


if __name__ == "__main__":
    # 用法:python main.py            → 抓今天
    #       python main.py 20260713   → 抓指定日
    run(sys.argv[1] if len(sys.argv) > 1 else None)
