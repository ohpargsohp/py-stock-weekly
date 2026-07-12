import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num(s):
    return float(str(s).replace(",", "").strip() or 0)


class MarginBalanceProvider(DataProvider):
    """個股融資融券餘額(MI_MARGN),僅取 config.WATCHLIST 內的股票。"""

    name = "margin_balance"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "margin_balance": "INTEGER",      # 融資今日餘額(張)
        "margin_balance_chg": "INTEGER",  # 融資餘額較前日增減(張)
        "short_balance": "INTEGER",       # 融券今日餘額(張)
        "short_balance_chg": "INTEGER",   # 融券餘額較前日增減(張)
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?response=json&date={date_str}&selectType=ALL"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        j = r.json()
        if j.get("stat") != "OK" or len(j.get("tables", [])) < 2:
            log.warning(f"{date_str} 融資融券無資料(可能休市)")
            return []

        # tables[1] 欄位:代號,名稱,融資(買進,賣出,現金償還,前日餘額,今日餘額,限額),
        #                    融券(買進,賣出,現券償還,前日餘額,今日餘額,限額),資券互抵,註記
        out = []
        for row in j["tables"][1]["data"]:
            sid = row[0].strip()
            if sid in config.WATCHLIST:
                margin_prev, margin_bal = int(_to_num(row[5])), int(_to_num(row[6]))
                short_prev, short_bal = int(_to_num(row[11])), int(_to_num(row[12]))
                out.append({
                    "trade_date": date_str,
                    "stock_id": sid,
                    "stock_name": config.WATCHLIST[sid],
                    "margin_balance": margin_bal,
                    "margin_balance_chg": margin_bal - margin_prev,
                    "short_balance": short_bal,
                    "short_balance_chg": short_bal - short_prev,
                })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 融資餘額 {r['margin_balance']:,}張"
            f"({r['margin_balance_chg']:+d}) | 融券餘額 {r['short_balance']:,}張({r['short_balance_chg']:+d})"
            for r in rows
        )
