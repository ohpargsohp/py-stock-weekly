import logging

import requests

import config
from core.base import DataProvider

log = logging.getLogger(__name__)
HEADERS = {"User-Agent": "Mozilla/5.0"}


def _to_num_or_none(s):
    s = str(s).replace(",", "").strip()
    if s in ("", "-"):
        return None
    return float(s)


class StockQuoteProvider(DataProvider):
    """個股收盤價 + 本益比 + 股價淨值比(BWIBBU_d),僅取 config.WATCHLIST 內的股票。
    無獲利公司本益比為'-',會存成 NULL,不是 0——別把「沒有」讀成「PE=0」。"""

    name = "stock_quote"
    pk = ["trade_date", "stock_id"]
    schema = {
        "trade_date": "TEXT",
        "stock_id": "TEXT",
        "stock_name": "TEXT",
        "close": "REAL",
        "dividend_yield": "REAL",
        "pe": "REAL",
        "pb": "REAL",
    }

    def fetch(self, date_str):
        url = f"https://www.twse.com.tw/rwd/zh/afterTrading/BWIBBU_d?response=json&date={date_str}&selectType=ALL"
        r = requests.get(url, headers=HEADERS, timeout=20)
        r.encoding = "utf-8"
        j = r.json()
        if j.get("stat") != "OK" or not j.get("data"):
            log.warning(f"{date_str} 個股股價/本益比無資料(可能休市)")
            return []

        out = []
        for row in j["data"]:
            sid = row[0].strip()
            if sid in config.WATCHLIST:
                out.append({
                    "trade_date": date_str,
                    "stock_id": sid,
                    "stock_name": config.WATCHLIST[sid],
                    "close": _to_num_or_none(row[2]),
                    "dividend_yield": _to_num_or_none(row[3]),
                    "pe": _to_num_or_none(row[5]),
                    "pb": _to_num_or_none(row[6]),
                })
        return out

    def describe(self, rows):
        if not rows:
            return None
        return "\n".join(
            f"   {r['stock_name']}({r['stock_id']}) 收盤 {r['close']} "
            f"| PE {r['pe'] if r['pe'] is not None else '—'} "
            f"| PB {r['pb'] if r['pb'] is not None else '—'}"
            for r in rows
        )
